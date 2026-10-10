"""Testes determinísticos do RAG (Exercícios 6 e 7): sem rede e sem modelo de embedding real.

Os vetores vêm de um embedding falso por saco de palavras — suficiente para testar o código de
índice, portão, citação e contrato de saída, que não dependem da qualidade semântica do vetor.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from src.core.prompts import carregar_prompt
from src.rag.avaliacao import (
    Pergunta,
    carregar_perguntas,
    escolher_limiar,
    evidencia_intacta_no_indice,
    posicao_da_evidencia,
    recall_at_k,
    varrer_limiares,
)
from src.rag.chunking import (
    Trecho,
    cortar_com_sobreposicao,
    cortar_corpus,
    cortar_por_caracteres,
    cortar_por_estrutura,
)
from src.rag.corpus import Documento, carregar_corpus, ler_documento, normalizar_espacos
from src.rag.embeddings import ModeloEmbedding
from src.rag.indice import IndiceVetorial, Resultado, somente_vigentes
from src.rag.resposta import (
    PipelineRAG,
    ids_citados_no_texto,
    interpretar_saida,
    montar_contexto,
    verificar_citacoes,
)


class EmbeddingFalso(ModeloEmbedding):
    """Saco de palavras normalizado sobre um vocabulário fixo: determinístico e sem download."""

    nome = "falso:bow"

    def __init__(self, vocabulario: list[str]) -> None:
        self.vocabulario = vocabulario

    def _embed(self, textos: list[str]) -> np.ndarray:
        linhas = []
        for t in textos:
            palavras = re.findall(r"\w+", t.lower())
            v = np.array([palavras.count(w) for w in self.vocabulario], dtype=np.float32) + 1e-3
            linhas.append(v / np.linalg.norm(v))
        return np.array(linhas, dtype=np.float32)


def _doc(corpo: str, id_: str = "doc-teste", revogado: str | None = None) -> Documento:
    return Documento(
        id=id_, titulo="Documento de teste", tipo="politica", versao="1", vigente_desde="2026-01-01",
        revogado_em=revogado, dono="teste", corpo=corpo, caminho=Path(f"{id_}.md"),
    )


# ------------------------------------------------------------------ corpus
def test_corpus_real_carrega_e_tem_documento_revogado():
    docs = carregar_corpus()
    assert len(docs) == 12
    revogados = [d.id for d in docs if not d.vigente]
    assert revogados == ["politica-precificacao-2025"]


def test_ler_documento_rejeita_id_diferente_do_arquivo(tmp_path):
    caminho = tmp_path / "nome-a.md"
    caminho.write_text(
        "---\nid: nome-b\ntitulo: t\ntipo: faq\nversao: 1\nvigente_desde: 2026-01-01\nrevogado_em:\ndono: x\n---\ncorpo",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="difere"):
        ler_documento(caminho)


def test_ler_documento_exige_metadados(tmp_path):
    caminho = tmp_path / "x.md"
    caminho.write_text("---\nid: x\n---\ncorpo", encoding="utf-8")
    with pytest.raises(ValueError, match="metadados ausentes"):
        ler_documento(caminho)


# ---------------------------------------------------------------- chunking
def test_cortes_por_caracteres_cobrem_o_texto_inteiro():
    corpo = "abcdefghij" * 50  # 500 caracteres
    trechos = cortar_por_caracteres(_doc(corpo), tamanho=120)
    assert "".join(t.texto for t in trechos) == corpo
    assert all(len(t.texto) <= 120 for t in trechos)


def test_sobreposicao_repete_a_borda():
    corpo = "".join(chr(65 + i % 26) for i in range(300))
    trechos = cortar_com_sobreposicao(_doc(corpo), tamanho=100, sobreposicao=30)
    for a, b in zip(trechos, trechos[1:]):
        assert a.texto[-30:] == b.texto[:30]
    assert trechos[-1].texto.endswith(corpo[-10:])


def test_sobreposicao_maior_que_bloco_e_erro():
    with pytest.raises(ValueError):
        cortar_com_sobreposicao(_doc("x" * 50), tamanho=10, sobreposicao=10)


def test_estrutura_herda_titulo_e_secao():
    corpo = "# Título\n\nIntro.\n\n## Art. 1 — Regra\n\nTexto da regra.\n\n## Art. 2 — Exceção\n\nTexto da exceção."
    trechos = cortar_por_estrutura(_doc(corpo))
    assert [t.secao for t in trechos] == ["Introdução", "Art. 1 — Regra", "Art. 2 — Exceção"]
    assert trechos[2].texto.startswith("Documento de teste — Art. 2 — Exceção")
    assert trechos[2].id == "doc-teste#s03"
    assert trechos[2].metadados["secao"] == "Art. 2 — Exceção"


def test_estrutura_quebra_secao_grande_por_paragrafo():
    corpo = "## Seção longa\n\n" + "\n\n".join("p" * 400 for _ in range(5))
    trechos = cortar_por_estrutura(_doc(corpo), maximo=1000)
    assert [t.id for t in trechos] == [f"doc-teste#s01.{i}" for i in range(1, 6)]


def test_ids_de_trecho_sao_unicos_no_corpus_real():
    docs = carregar_corpus()
    for estrategia in ("caracteres", "caracteres+overlap", "estrutura"):
        ids = [t.id for t in cortar_corpus(docs, estrategia)]
        assert len(ids) == len(set(ids)), estrategia


# ------------------------------------------------- conjunto de perguntas
def test_conjunto_de_perguntas_cumpre_a_composicao_do_enunciado():
    perguntas = carregar_perguntas()
    assert len(perguntas) >= 10
    assert sum(p.tipo == "excecao" for p in perguntas) >= 2
    assert sum(not p.tem_resposta for p in perguntas) >= 3
    for p in perguntas:
        assert p.tem_resposta == bool(p.evidencias), p.id
        if p.tem_resposta:
            assert p.resposta_referencia, p.id


def test_toda_evidencia_existe_literalmente_no_documento_rotulado():
    por_id = {d.id: d for d in carregar_corpus()}
    for p in carregar_perguntas():
        if not p.tem_resposta:
            continue
        corpo = normalizar_espacos(por_id[p.doc_id].corpo)
        assert normalizar_espacos(p.evidencias[0]) in corpo, p.id


def test_evidencia_intacta_detecta_corte_no_meio():
    p = Pergunta("X", "?", True, "simples", "doc-teste", ("regra importante",))
    inteiro = [Trecho("a#1", "a", "uma regra importante aqui", "")]
    partido = [Trecho("a#1", "a", "uma regra imp", ""), Trecho("a#2", "a", "ortante aqui", "")]
    assert evidencia_intacta_no_indice(inteiro, p)
    assert not evidencia_intacta_no_indice(partido, p)


def test_recall_at_k_conta_none_como_falha():
    assert recall_at_k({"a": 1, "b": 3, "c": None, "d": 5}, 3) == 0.5
    assert recall_at_k({}, 3) == 0.0


# ------------------------------------------------------------------ índice
@pytest.fixture
def indice_pequeno():
    trechos = [
        Trecho("p#s01", "p", "desconto maximo referencia quinze", "a", {"revogado_em": None}),
        Trecho("p#s02", "p", "desconto maximo generico quarenta", "b", {"revogado_em": None}),
        Trecho("v#s01", "v", "desconto maximo referencia dez", "a", {"revogado_em": "2026-03-01"}),
        Trecho("f#s01", "f", "coleta roda de madrugada", "c", {"revogado_em": None}),
    ]
    vocabulario = ["desconto", "maximo", "referencia", "generico", "quinze", "quarenta", "dez", "coleta", "madrugada"]
    modelo = EmbeddingFalso(vocabulario)
    return IndiceVetorial.construir(trechos, modelo, "teste"), modelo


def test_busca_ordena_por_distancia_e_respeita_k(indice_pequeno):
    indice, modelo = indice_pequeno
    r = indice.buscar(modelo.embed_consultas(["coleta madrugada"])[0], k=2)
    assert [x.trecho.id for x in r][0] == "f#s01"
    assert [x.posicao for x in r] == [1, 2]
    assert r[0].distancia <= r[1].distancia


def test_filtro_de_metadado_exclui_revogado_antes_da_similaridade(indice_pequeno):
    indice, modelo = indice_pequeno
    v = modelo.embed_consultas(["desconto maximo referencia dez"])[0]
    assert indice.buscar(v, k=1)[0].trecho.id == "v#s01"
    assert indice.buscar(v, k=1, filtro=somente_vigentes)[0].trecho.id == "p#s01"


def test_indice_persiste_e_recarrega_identico(indice_pequeno, tmp_path):
    indice, modelo = indice_pequeno
    caminho = tmp_path / "i.db"
    indice.salvar(caminho)
    recarregado = IndiceVetorial.carregar(caminho)
    assert [t.id for t in recarregado.trechos] == [t.id for t in indice.trechos]
    assert np.allclose(recarregado.vetores, indice.vetores)
    assert recarregado.carimbo["chunking"] == "teste"
    assert recarregado.trechos[2].metadados["revogado_em"] == "2026-03-01"


def test_posicao_da_evidencia(indice_pequeno):
    indice, modelo = indice_pequeno
    p = Pergunta("X", "?", True, "simples", "p", ("generico quarenta",))
    r = indice.buscar(modelo.embed_consultas(["desconto maximo"])[0], k=4)
    assert posicao_da_evidencia(r, p) == next(x.posicao for x in r if x.trecho.id == "p#s02")


# ------------------------------------------------------------------ portão
def _perguntas_portao():
    return [
        Pergunta("C1", "?", True, "simples", "d", ("e",)),
        Pergunta("C2", "?", True, "simples", "d", ("e",)),
        Pergunta("S1", "?", False, "sem_resposta", None, ()),
        Pergunta("S2", "?", False, "sem_resposta", None, ()),
    ]


def test_limiar_escolhido_nao_barra_pergunta_com_resposta():
    distancias = {"C1": 0.10, "C2": 0.15, "S1": 0.16, "S2": 0.30}
    pontos = varrer_limiares(distancias, _perguntas_portao(), [0.12, 0.155, 0.20])
    escolhido = escolher_limiar(pontos)
    assert escolhido.limiar == 0.155
    assert escolhido.barradas_com_resposta == 0
    assert escolhido.barradas_sem_resposta == 2


def test_limiar_none_quando_nenhum_separa_sem_falso_negativo():
    distancias = {"C1": 0.40, "C2": 0.15, "S1": 0.16, "S2": 0.30}
    pontos = varrer_limiares(distancias, _perguntas_portao(), [0.12, 0.2])
    assert escolher_limiar(pontos) is None


# ---------------------------------------------------- citação e contrato
def test_verificar_citacoes_separa_inventadas():
    validas, invalidas = verificar_citacoes(["a#s01", "b#s09"], ["a#s01", "a#s02"])
    assert validas == ["a#s01"]
    assert invalidas == ["b#s09"]


def test_ids_citados_no_texto():
    texto = "Conforme [politica-precificacao-2026#s02] e regras-ruptura#s03.1, sim."
    assert ids_citados_no_texto(texto) == ["politica-precificacao-2026#s02", "regras-ruptura#s03.1"]


@pytest.mark.parametrize(
    "conteudo, erro",
    [
        ("não é json", "JSON inválido"),
        ("[1, 2]", "não é um objeto"),
        ('{"resposta": "x"}', "chaves ausentes"),
        ('{"resposta": "x", "citacoes": "a#s01", "recusou": false}', "não é lista"),
    ],
)
def test_interpretar_saida_fora_do_contrato(conteudo, erro):
    assert erro in interpretar_saida(conteudo)["erro_contrato"]


def test_montar_contexto_inverte_ordem():
    r = [
        Resultado(Trecho("a#s01", "a", "A", ""), 0.1, 1),
        Resultado(Trecho("b#s01", "b", "B", ""), 0.2, 2),
    ]
    assert montar_contexto(r).startswith("[a#s01]")
    assert montar_contexto(r, "invertida").startswith("[b#s01]")


def test_prompt_de_resposta_versionado_e_sem_marcador_pendente():
    prompt = carregar_prompt("resposta_rag_v1")
    assert prompt.versao.startswith("v1")
    texto = prompt.preencher(contexto="[x#s01]\nabc", pergunta="?")
    assert "{{" not in texto
    with pytest.raises(ValueError, match="marcadores sem valor"):
        prompt.preencher(pergunta="?")


# ------------------------------------------------- pipeline com LLM falso
class ClienteFalso:
    """Imita client.chat.completions.create devolvendo um conteúdo fixo e contando chamadas."""

    def __init__(self, conteudo: str, finish_reason: str = "stop") -> None:
        self.chamadas = 0
        self.ultima_mensagem = None
        conteudo_fixo, motivo = conteudo, finish_reason

        def create(**kwargs):
            self.chamadas += 1
            self.ultima_mensagem = kwargs["messages"][0]["content"]
            return SimpleNamespace(
                choices=[SimpleNamespace(finish_reason=motivo, message=SimpleNamespace(content=conteudo_fixo))],
                usage=SimpleNamespace(total_tokens=42),
            )

        self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))


def test_portao_barra_sem_chamar_o_modelo(indice_pequeno):
    indice, modelo = indice_pequeno
    cliente = ClienteFalso("{}")
    pipeline = PipelineRAG(indice, modelo, cliente, "falso", k=2, limiar=0.0001)
    r = pipeline.responder("coleta madrugada desconto generico")
    assert r.barrado_pelo_portao and r.recusou
    assert cliente.chamadas == 0
    assert "mais próximo" in r.resposta and r.recuperados[0].trecho.id in r.resposta


def test_pipeline_confere_citacao_inventada(indice_pequeno):
    indice, modelo = indice_pequeno
    saida = json.dumps({"resposta": "Quinze por cento [p#s01].", "citacoes": ["p#s01", "zz#s99"], "recusou": False})
    cliente = ClienteFalso(saida)
    pipeline = PipelineRAG(indice, modelo, cliente, "falso", k=2, limiar=1.0)
    r = pipeline.responder("desconto maximo referencia")
    assert cliente.chamadas == 1
    assert r.citacoes_validas == ["p#s01"]
    assert r.citacoes_invalidas == ["zz#s99"]
    assert "[p#s01]" in cliente.ultima_mensagem


def test_pipeline_trata_corte_por_max_tokens_como_erro(indice_pequeno):
    indice, modelo = indice_pequeno
    cliente = ClienteFalso('{"resposta": "x", "citacoes": [], "recusou": false}', finish_reason="length")
    r = PipelineRAG(indice, modelo, cliente, "falso", k=2, limiar=1.0).responder("desconto")
    assert r.trace["decisao"] == "erro_contrato"
    assert r.resposta == ""


def test_portao_desligado_chama_o_modelo_mesmo_longe(indice_pequeno):
    indice, modelo = indice_pequeno
    cliente = ClienteFalso('{"resposta": "x", "citacoes": [], "recusou": true}')
    pipeline = PipelineRAG(indice, modelo, cliente, "falso", k=2, limiar=0.0001)
    r = pipeline.responder("desconto", portao=False)
    assert cliente.chamadas == 1 and not r.barrado_pelo_portao
    assert r.trace["carimbo"]["portao"] == "desligado"


# ------------------------------------------------- prompts versionados
@pytest.mark.parametrize("nome", ["resposta_rag_v1", "juiz_fidelidade_rag_v1", "juiz_fundamentacao_v1", "analista_bi_v2"])
def test_prompt_enviado_nao_carrega_documentacao(nome):
    p = carregar_prompt(nome)
    assert "<!--" not in p.texto and "**Versão:**" not in p.texto and "O que cada frase impede" not in p.texto


def test_marcador_citado_na_documentacao_nao_divide_o_arquivo(tmp_path):
    (tmp_path / "x.md").write_text(
        '<!-- tudo antes do heading "## Prompt enviado ao modelo" é doc -->\n**Versão:** v1.0\n\n'
        "## Prompt enviado ao modelo\n\nTEXTO REAL", encoding="utf-8")
    p = carregar_prompt("x", pasta=tmp_path)
    assert p.texto == "TEXTO REAL" and p.versao == "v1.0"


def test_prompt_v1_da_parte1_e_o_mesmo_texto_que_a_v2_menos_a_regra_nova():
    from src.projects.farmacia_precos.system_prompt import carregar_prompt_sistema
    v1, v2 = carregar_prompt_sistema(), carregar_prompt("analista_bi_v2").texto
    assert v1.startswith("Você é um agente de BI")
    assert "consultar_base_conhecimento" in v2 and "consultar_base_conhecimento" not in v1
    assert set(v1.splitlines()) <= set(v2.splitlines())


def test_citacao_com_colchetes_e_o_mesmo_id_mas_inventada_continua_invalida():
    validas, invalidas = verificar_citacoes(["[a#s01]", " [zz#s09] "], ["a#s01"])
    assert validas == ["a#s01"] and invalidas == ["zz#s09"]


def test_json_rejeitado_pelo_provedor_vira_erro_de_contrato(indice_pequeno):
    import httpx
    from openai import BadRequestError

    indice, modelo = indice_pequeno
    cliente = ClienteFalso("{}")

    def create(**kwargs):
        resposta = httpx.Response(400, request=httpx.Request("POST", "http://x"))
        raise BadRequestError("Failed to validate JSON", response=resposta, body={"code": "json_validate_failed"})

    cliente.chat.completions.create = create
    r = PipelineRAG(indice, modelo, cliente, "falso", k=2, limiar=1.0).responder("desconto")
    assert r.trace["decisao"] == "erro_contrato" and r.resposta == ""
