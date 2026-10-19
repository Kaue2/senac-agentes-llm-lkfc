"""Testes determinísticos do grafo da Parte 2: sem rede e sem LLM. O modelo é um falso que devolve
respostas roteirizadas; o grafo, os nós, as rotas, o checkpointer e a ferramenta de exportação são
os de verdade."""

from __future__ import annotations

import json
import typing
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from src.core.prompts import PromptVersionado
from src.core.tools import Ferramenta, RegistroFerramentas
from src.grafo.dependencias import Dependencias, Tetos
from src.grafo.estado import EstadoGrafo
from src.grafo.falsos import ModeloFalso, chamada, resposta, triagem_json
from src.grafo.execucao import executar_turno, expirar_pendentes, listar_pendentes, retomar
from src.grafo.grafo import construir_grafo, obter_grafo
from src.projects.farmacia_precos.tools_farmacia import _exportar_analise


# ------------------------------------------------------------------ modelo falso
_msg = resposta
_call = chamada


class Relogio:
    def __init__(self):
        self.t = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.t


PROMPT = PromptVersionado("teste", "v0", "prompt de teste", None)


@pytest.fixture
def ambiente(tmp_path):
    exports = tmp_path / "exports"
    registro = RegistroFerramentas()
    registro.registrar(Ferramenta(
        "consultar_precos", "preços", {"type": "object", "properties": {"produto": {"type": "string"}}},
        lambda produto, farmacia="", modo="atual": (
            {"encontrado": True, "fonte": "espelho_sqlite", "resultados": [{"Produto": produto, "Farmacia": "Drogasil", "PrecoFarmacia": 322.15, "DataUltimaColeta": "2026-09-19"}]}
            if produto != "Inexistente" else {"encontrado": False, "fonte": "espelho_sqlite", "mensagem": "nada"}),
        "leitura", True, "falso"))
    registro.registrar(Ferramenta(
        "exportar_analise", "exporta", {"type": "object"},
        lambda pergunta, dados_resumo, explicacao: _exportar_analise(pergunta, dados_resumo, explicacao, exports),
        "escrita", True, "disco"))
    relogio = Relogio()
    modelo = ModeloFalso()
    deps = Dependencias(cliente=modelo, modelo="falso", ferramentas=registro, prompt_agente=PROMPT,
                        prompt_triagem=PROMPT, fonte_dados="espelho_sqlite", memoria=None,
                        tetos=Tetos(max_passos=4, max_segundos=10_000), agora=relogio)
    grafo = obter_grafo(tmp_path / "cp.db")
    return SimpleNamespace(deps=deps, modelo=modelo, grafo=grafo, exports=exports, relogio=relogio, logs=tmp_path / "logs")


def turno(amb, texto, sessao="s1"):
    return executar_turno(texto, amb.deps, "G-0042", sessao, grafo=amb.grafo, pasta_logs=amb.logs)


# ------------------------------------------------------------------------- testes
def test_caminho_feliz_saida_validada_com_fonte(ambiente):
    ambiente.modelo.triagens = [triagem_json(suposicoes=["preço = PrecoFarmacia"])]
    ambiente.modelo.passos = [_msg(tool_calls=[_call("consultar_precos", {"produto": "Trayenta 5mg", "farmacia": "Drogasil"})]),
                              _msg("Na Drogasil, Trayenta 5mg: R$ 322,15 (PrecoFarmacia).")]
    r = turno(ambiente, "preço da trayenta na drogasil")
    assert r.saida.suficiencia == "suficiente"
    assert r.saida.fontes[0].tipo == "banco_precos" and "vw_PrecoAtual" in r.saida.fontes[0].referencia
    assert r.saida.suposicoes == ["preço = PrecoFarmacia"]
    assert r.saida.motivo_terminacao == "resposta_final"
    log = json.loads(r.caminho_log.read_text(encoding="utf-8"))
    assert {"commit", "modelo", "prompt_agente", "langgraph", "recursion_limit"} <= set(log["carimbo"])
    assert log["medicoes"]["paralelo"]["soma_ms"] >= 0


def test_registro_inexistente_e_insuficiente(ambiente):
    ambiente.modelo.triagens = [triagem_json()]
    ambiente.modelo.passos = [_msg(tool_calls=[_call("consultar_precos", {"produto": "Inexistente"})]),
                              _msg("Não encontrei esse produto no cadastro.")]
    r = turno(ambiente, "preço do Inexistente")
    assert r.saida.suficiencia == "insuficiente"
    assert "nenhum registro" in r.saida.motivo_insuficiencia


def test_fora_do_escopo_nao_chama_o_agente(ambiente):
    ambiente.modelo.triagens = [triagem_json("fora_escopo", pilar="nenhum", justificativa="dado de paciente")]
    r = turno(ambiente, "o que a dona Maria comprou?")
    assert ambiente.modelo.chamadas_agente == 0
    assert r.saida.suficiencia == "insuficiente" and r.saida.motivo_terminacao == "fora_do_escopo"
    assert "Eu respondo sobre" in r.saida.resultado  # recusa dizendo o que o sistema faz


def test_esclarece_uma_vez_e_recusa_na_segunda(ambiente):
    ambiente.modelo.triagens = [
        triagem_json("esclarecer", faltando=["produto"], pergunta_esclarecimento="Qual produto?"),
        triagem_json("esclarecer", faltando=["produto"], pergunta_esclarecimento="Qual produto mesmo?"),
    ]
    r1 = turno(ambiente, "quanto tá o remédio?")
    assert r1.saida.suficiencia == "aguardando_esclarecimento" and r1.saida.pergunta_esclarecimento == "Qual produto?"
    r2 = turno(ambiente, "aquele lá")
    assert r2.saida.motivo_terminacao == "recorte_insuficiente"
    assert ambiente.modelo.chamadas_agente == 0


def test_conversa_acumula_e_turno_zera_trajetoria(ambiente):
    ambiente.modelo.triagens = [triagem_json(), triagem_json()]
    ambiente.modelo.passos = [_msg(tool_calls=[_call("consultar_precos", {"produto": "A"})]), _msg("ok A"),
                              _msg(tool_calls=[_call("consultar_precos", {"produto": "B"})]), _msg("ok B")]
    turno(ambiente, "preço de A")
    r = turno(ambiente, "e de B?")
    assert [m["texto"] for m in r.estado["mensagens"]] == ["preço de A", "ok A", "e de B?", "ok B"]
    chamadas = [p for p in r.estado["trajetoria"] if p.get("tipo") == "chamada_ferramenta"]
    assert [c["argumentos"]["produto"] for c in chamadas] == ["B"]
    assert r.saida.turno == 2


def test_laco_detectado_antes_do_teto(ambiente):
    ambiente.deps.tetos = Tetos(max_passos=8, max_segundos=10_000, limite_repeticao=2)
    ambiente.modelo.triagens = [triagem_json()]
    ambiente.modelo.passos = [_msg(tool_calls=[_call("consultar_precos", {"produto": "X"}, f"c{i}")]) for i in range(5)]
    r = turno(ambiente, "preço de X")
    assert r.saida.motivo_terminacao.startswith("laco_detectado")
    assert ambiente.modelo.chamadas_agente == 3


def test_teto_de_passos(ambiente):
    ambiente.modelo.triagens = [triagem_json()]
    ambiente.modelo.passos = [_msg(tool_calls=[_call("consultar_precos", {"produto": f"P{i}"}, f"c{i}")]) for i in range(10)]
    r = turno(ambiente, "preço de tudo")
    assert r.saida.motivo_terminacao == "orcamento_excedido_passos (4/4)"
    assert r.saida.suficiencia == "insuficiente"


def test_entrada_vazia_nao_chama_modelo(ambiente):
    r = turno(ambiente, "   ")
    assert r.saida.motivo_terminacao == "entrada_vazia" and ambiente.modelo.chamadas_agente == 0


def _pedir_exportacao(amb, sessao="s1"):
    amb.modelo.triagens = [triagem_json()]
    amb.modelo.passos = [
        _msg(tool_calls=[_call("consultar_precos", {"produto": "Trayenta 5mg"}, "c1")]),
        _msg(tool_calls=[_call("exportar_analise", {"pergunta": "p", "dados_resumo": "R$ 322,15", "explicacao": "e"}, "c2")]),
    ]
    return turno(amb, "preço da trayenta e salva a análise", sessao)


def test_pausa_aprova_editando_e_segunda_aprovacao_nao_duplica(ambiente):
    r = _pedir_exportacao(ambiente)
    assert r.saida.suficiencia == "aguardando_aprovacao"
    assert r.interrupcao["acao"] == "exportar_analise" and "prazo_expira_em" in r.interrupcao
    assert not ambiente.exports.exists()  # nada escrito antes da aprovação
    pendente_cp = ambiente.grafo.get_state({"configurable": {"thread_id": r.thread_id}}).config["configurable"]["checkpoint_id"]

    decisao = {"decisao": "editar", "argumentos": {"explicacao": "editada pelo revisor"}, "revisor": "adm-01"}
    ambiente.modelo.passos = [_msg("Exportei a análise.")]
    r1 = retomar(r.thread_id, decisao, ambiente.deps, ambiente.grafo, pasta_logs=ambiente.logs)
    assert r1.saida.acoes_executadas[0].ja_existia is False
    assert r1.saida.acoes_executadas[0].argumentos["explicacao"] == "editada pelo revisor"
    assert len(list(ambiente.exports.glob("*.md"))) == 1

    ambiente.modelo.passos = [_msg("Exportei a análise.")]
    r2 = retomar(r.thread_id, decisao, ambiente.deps, ambiente.grafo, checkpoint_id=pendente_cp, pasta_logs=ambiente.logs)
    assert r2.saida.acoes_executadas[0].ja_existia is True
    assert r2.saida.acoes_executadas[0].chave_idempotencia == r1.saida.acoes_executadas[0].chave_idempotencia
    assert len(list(ambiente.exports.glob("*.md"))) == 1


def test_rejeitar_volta_ao_agente_sem_escrever(ambiente):
    r = _pedir_exportacao(ambiente)
    ambiente.modelo.passos = [_msg("Ok, não exportei.")]
    r1 = retomar(r.thread_id, {"decisao": "rejeitar", "comentario": "não precisa"}, ambiente.deps, ambiente.grafo, pasta_logs=ambiente.logs)
    assert r1.saida.acoes_executadas == [] and not ambiente.exports.exists()
    assert r1.saida.motivo_terminacao == "resposta_final"


def test_resposta_invalida_pausa_de_novo(ambiente):
    r = _pedir_exportacao(ambiente)
    r1 = retomar(r.thread_id, {"decisao": "talvez"}, ambiente.deps, ambiente.grafo, pasta_logs=ambiente.logs)
    assert r1.interrupcao is not None and r1.saida.suficiencia == "aguardando_aprovacao"


def test_prazo_vencido_expira_sem_exportar(ambiente):
    r = _pedir_exportacao(ambiente)
    assert [p["thread_id"] for p in listar_pendentes(ambiente.grafo)] == [r.thread_id]
    ambiente.relogio.t += timedelta(hours=25)
    resultados = expirar_pendentes(ambiente.deps, ambiente.grafo, pasta_logs=ambiente.logs)
    assert resultados[0].saida.motivo_terminacao == "aprovacao_expirada"
    assert not ambiente.exports.exists() and listar_pendentes(ambiente.grafo) == []


def test_aprovacao_atrasada_vira_expiracao(ambiente):
    r = _pedir_exportacao(ambiente)
    ambiente.relogio.t += timedelta(hours=30)
    r1 = retomar(r.thread_id, {"decisao": "aprovar"}, ambiente.deps, ambiente.grafo, pasta_logs=ambiente.logs)
    assert r1.saida.motivo_terminacao == "aprovacao_expirada" and not ambiente.exports.exists()


def test_mensagem_nova_com_pausa_pendente_nao_descarta_a_pausa(ambiente):
    r = _pedir_exportacao(ambiente)
    r1 = turno(ambiente, "outra pergunta")
    assert r1.interrupcao is not None and r1.interrupcao["chave_idempotencia"] == r.interrupcao["chave_idempotencia"]


def test_campos_com_mais_de_um_escritor_tem_reducer():
    """Confere a coluna 'quem escreve' de docs/grafo.md §4 contra o código: todo campo escrito por
    mais de um nó, ou pelos dois ramos paralelos, tem reducer."""
    import ast
    import inspect

    from src.grafo import nos

    escritores: dict[str, set[str]] = {}
    for nome in construir_grafo().nodes:
        arvore = ast.parse(inspect.getsource(getattr(nos, nome)))
        # Atualizações de estado: o dict devolvido por `return {...}`, o dict `atualizacao` e as
        # atribuições `atualizacao["campo"] = ...`. Dicts aninhados (ex.: `usada`) não contam.
        chaves: list[ast.expr] = []
        for no in ast.walk(arvore):
            if isinstance(no, ast.Return) and isinstance(no.value, ast.Dict):
                chaves += no.value.keys
            elif isinstance(no, ast.AnnAssign) and getattr(no.target, "id", "") == "atualizacao" and isinstance(no.value, ast.Dict):
                chaves += no.value.keys
            elif isinstance(no, ast.Assign) and isinstance(no.targets[0], ast.Subscript) and getattr(no.targets[0].value, "id", "") == "atualizacao":
                chaves.append(no.targets[0].slice)
        for chave in chaves:
            if isinstance(chave, ast.Constant) and chave.value in EstadoGrafo.__annotations__:
                escritores.setdefault(chave.value, set()).add(nome)
    dicas = typing.get_type_hints(EstadoGrafo, include_extras=True)
    com_reducer = {c for c, t in dicas.items() if typing.get_origin(t) is typing.Annotated}
    paralelos = {"carregar_memoria", "triagem"}
    for campo, nos_ in escritores.items():
        if len(nos_ & paralelos) == 2:
            assert campo in com_reducer, f"{campo} é escrito pelos dois ramos paralelos sem reducer"
    assert {"eventos", "trajetoria"} <= com_reducer


def test_remocao_por_titular_alcanca_memoria_checkpoint_e_log(ambiente, tmp_path):
    """§5.4: grava (memória + checkpoint + log), confere que o comportamento mudou, remove, e varre
    as estruturas procurando a matrícula — inclusive os BYTES do arquivo de checkpoint."""
    from src.grafo.execucao import remover_titular
    from src.memoria.memoria import Memoria
    from src.rag.embeddings import EmbeddingComCache
    from tests.test_memoria import EmbeddingFalso

    ambiente.deps.memoria = Memoria(EmbeddingComCache(EmbeddingFalso(), caminho=tmp_path / "cache.db"), tmp_path / "memoria")
    ambiente.modelo.triagens = [triagem_json(), triagem_json()]
    ambiente.modelo.passos = [_msg(tool_calls=[_call("consultar_precos", {"produto": "Trayenta", "farmacia": "Raia"})]), _msg("ok"),
                              _msg(tool_calls=[_call("consultar_precos", {"produto": "Trayenta", "farmacia": "Raia"})]), _msg("ok")]
    turno(ambiente, "Minha farmácia padrão é a Raia. Preço da Trayenta?", "a")
    r = turno(ambiente, "preço da trayenta", "b")
    assert r.estado["memoria_usada"]["fatos"] == {"usuario:G-0042:farmacia_padrao": "Raia"}  # comportamento mudou

    relatorio = remover_titular("G-0042", ambiente.deps, ambiente.grafo, pastas_logs=[ambiente.logs])
    assert sorted(relatorio["threads_de_checkpoint_apagadas"]) == ["G-0042:a", "G-0042:b"]
    pastas = [tmp_path / "memoria", ambiente.logs, tmp_path]  # tmp_path contém o cp.db do checkpointer
    assert ambiente.deps.memoria.varrer("G-0042", pastas) == []

    ambiente.modelo.triagens = [triagem_json()]
    ambiente.modelo.passos = [_msg("qual farmácia?")]
    r2 = turno(ambiente, "preço da trayenta", "c")
    assert r2.estado["memoria_usada"]["fatos"] == {}  # voltou ao comportamento sem memória
