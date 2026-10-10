"""Exercício 8 (complementar) — a memória do case.

Uso: python scripts/aula08_memoria.py

Roda sobre uma memória de demonstração recriada do zero a cada execução (dados/memoria_demo/),
para o relatório ser reprodutível. As partes sem LLM (fronteira, estruturas, idempotência,
contradição, esquecimento no contexto) sempre rodam; as que comparam respostas do agente
(esquecimento e não reprodutibilidade observados na resposta) exigem o .env.
Saída em logs/aula08/saida.txt e detalhes em logs/aula08/memoria.json.

Parâmetros e justificativas:
- `GESTOR = "G-0042"`: identificador pseudônimo (matrícula) de um gestor. A memória nunca guarda
  nome nem e-mail — a matrícula basta para chavear, e é o que a remoção procura.
- `HISTORICO_SINTETICO`: 30 consultas passadas de dois gestores, espalhadas em 120 dias, para
  haver o que decair (corte de 90 dias). São SINTÉTICAS (declarado no relatório): o agente
  ainda não tem uso real que gere histórico.
- `HOJE = 2026-10-09`: fixo, para o decaimento ser reprodutível.
"""

from __future__ import annotations

import json
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv

load_dotenv()

import numpy as np  # noqa: E402

from src.core.budget import Orcamento  # noqa: E402
from src.core.llm_client import cliente_ativo_ou_none  # noqa: E402
from src.memoria.contexto import TETO_TOKENS_MEMORIA, contar_tokens, montar_contexto_memoria  # noqa: E402
from src.memoria.execucao import executar_com_memoria  # noqa: E402
from src.memoria.memoria import DIAS_DECAIMENTO_EPISODICA, Memoria, medir_ms  # noqa: E402
from src.memoria.politica import RecorteExtraido  # noqa: E402
from src.rag.embeddings import modelo_do_ambiente  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]
PASTA_DEMO = RAIZ / "dados" / "memoria_demo"
PASTA_CHECKPOINTS = PASTA_DEMO / "checkpoints"
PASTA_LOG = RAIZ / "logs" / "aula08"
GESTOR = "G-0042"
OUTRO_GESTOR = "G-0077"
HOJE = date(2026, 10, 9)
PERGUNTA_TESTE = "Qual o preço atual da Trayenta 5mg?"
LOGS_DE_EXECUCAO_REAIS = [
    "caso-01-simples.json", "caso-02-divergencia.json", "caso-03-registro-inexistente.json",
    "caso-04-nao-deve-exportar.json", "execucao_20260920T193104.json",
]

_PRODUTOS = ["Trayenta 5mg", "Linagliptina 5mg", "Ozempic 1mg", "Novalgina 500mg"]
_FARMACIAS = ["Drogasil", "Araujo", "Raia", "Pacheco", "Venancio"]
_MODOS = ["atual", "historico", "ruptura"]
_PERGUNTAS = {
    "atual": "Qual o preço atual da {p} na {f}?",
    "historico": "Como variou o preço da {p} na {f} no último mês?",
    "ruptura": "A {p} está em falta na {f}?",
}

_linhas: list[str] = []


def out(texto: str = "") -> None:
    print(texto)
    _linhas.append(texto)


def historico_sintetico() -> list[tuple[str, str, str, RecorteExtraido]]:
    """(gestor, data, pergunta, recorte) determinísticos: 30 consultas em 120 dias."""
    itens = []
    for i in range(30):
        gestor = GESTOR if i % 3 else OUTRO_GESTOR
        produto, farmacia, modo = _PRODUTOS[i % 4], _FARMACIAS[i % 5], _MODOS[i % 3]
        data = (HOJE - timedelta(days=4 * i)).isoformat()
        pergunta = _PERGUNTAS[modo].format(p=produto, f=farmacia)
        itens.append((gestor, data, pergunta,
                      RecorteExtraido(("consultar_precos",), (produto,), (farmacia,), (modo,), "resposta_final")))
    return itens


def main() -> None:
    shutil.rmtree(PASTA_DEMO, ignore_errors=True)
    embeddings = modelo_do_ambiente()
    memoria = Memoria(embeddings, pasta=PASTA_DEMO)
    registro: dict = {"hoje": HOJE.isoformat(), "modelo_embedding": embeddings.nome}

    # ----------------------------------------------------- população + fronteira
    for gestor, data, pergunta, recorte in historico_sintetico():
        memoria.gravar_episodio(gestor, data, pergunta, recorte)
    memoria.gravar_regra("Ao responder preço, cite sempre a farmácia e a data da coleta antes do número.", autor="time-bi")
    memoria.gravar_regra("Ao comparar farmácias, use PrecoFarmacia; PrecoPbm só quando o gestor pedir o preço do programa.", autor="time-bi")

    tokens_por_execucao = [contar_tokens((RAIZ / "logs" / n).read_text(encoding="utf-8")) for n in LOGS_DE_EXECUCAO_REAIS]
    media = sum(tokens_por_execucao) / len(tokens_por_execucao)
    n_execucoes = memoria.contar_episodios()
    contexto = montar_contexto_memoria(memoria, GESTOR, PERGUNTA_TESTE)
    out("FRONTEIRA")
    out(f"  arquivo morto ({n_execucoes} execuções serializadas) ... {round(media * n_execucoes)} tokens"
        f"   (média medida de {media:.0f} tokens/execução nos {len(tokens_por_execucao)} logs reais de logs/ × {n_execucoes})")
    out(f"  memória recuperada por relevância .......... {contexto.tokens} tokens   (teto {TETO_TOKENS_MEMORIA})")
    registro["fronteira"] = {"tokens_por_execucao_reais": tokens_por_execucao, "n_execucoes": n_execucoes,
                             "arquivo_morto_tokens": round(media * n_execucoes), "memoria_tokens": contexto.tokens}

    # --------------------------------------------------------- as três memórias
    memoria.gravar_fato(f"usuario:{GESTOR}:farmacia_padrao", "Drogasil", "2026-09-10", "declaração do gestor")
    ms_epi = medir_ms(memoria.buscar_episodios, GESTOR, PERGUNTA_TESTE)
    ms_sem = medir_ms(memoria.ler_fato, f"usuario:{GESTOR}:farmacia_padrao")
    out("\nAS TRÊS MEMÓRIAS")
    out(f"  episódica  {memoria.contar_episodios()} registros   consulta: {ms_epi:.1f} ms (embedding da pergunta já em cache)")
    out(f"  semântica  {memoria.contar_chaves()} chaves      consulta: {ms_sem:.2f} ms")
    out(f"  procedural {contar_tokens(memoria.texto_procedural())} tokens no system prompt")

    # ---------------------------------------------------------- política
    exemplo = memoria.texto_do_episodio(historico_sintetico()[1][2], historico_sintetico()[1][3])
    out("\nPOLÍTICA DE ESCRITA: o código extrai por regra; o humano corrige a semântica; procedural só humano")
    out(f"  volume por execução: 1 registro episódico (~{contar_tokens(exemplo)} tokens) + 0 ou 1 fato semântico")
    out("  o que NÃO entra: preço/ruptura devolvidos por ferramenta (derivável, envelhece em 24 h) · resposta do agente"
        " (não verificada) · trechos do RAG (derivável) · CPF/e-mail/telefone (mascarados) · dado de paciente · credenciais")

    # ---------------------------------------------------------- idempotência
    r1 = memoria.gravar_fato(f"usuario:{GESTOR}:alias:remedio de diabetes da boehringer", "Trayenta 5mg", "2026-10-01", "time-bi")
    r2 = memoria.gravar_fato(f"usuario:{GESTOR}:alias:remedio de diabetes da boehringer", "Trayenta 5mg", "2026-10-01", "time-bi")
    out("\nIDEMPOTÊNCIA")
    out(f"  1ª gravação -> {r1.id}  ja_existia={str(r1.ja_existia).lower()}")
    out(f"  2ª gravação -> {r2.id}  ja_existia={str(r2.ja_existia).lower()}")

    # ---------------------------------------------------------- contradição
    chave = f"usuario:{GESTOR}:farmacia_padrao"
    memoria.gravar_fato(chave, "Raia", "2026-10-02", "declaração do gestor")
    fato_a = "A farmácia padrão do gestor G-0042 é a Drogasil."
    fato_b = "A farmácia padrão do gestor G-0042 é a Raia."
    vetores = embeddings.embed_documentos([fato_a, fato_b])
    consulta = embeddings.embed_consultas(["Qual é a farmácia padrão do gestor G-0042?"])[0]
    sim_a, sim_b = (float(v @ consulta) for v in vetores)
    leitura = memoria.ler_fato(chave)
    out("\nCONTRADIÇÃO")
    out(f"  fato A [2026-09-10]: Drogasil   similaridade {sim_a:.4f}")
    out(f"  fato B [2026-10-02]: Raia       similaridade {sim_b:.4f}   (diferença {abs(sim_a - sim_b):.4f}: o vetor não ordena no tempo)")
    out(f"  desempate por carimbo: {leitura.vencedor.valor} (max(valido_desde)); descartado registrado em descartes.jsonl: "
        f"{[f.valor for f in leitura.descartados]}")
    registro["contradicao"] = {"sim_a": sim_a, "sim_b": sim_b, "vencedor": leitura.vencedor.valor}

    # ---------------------------------------------------------- decaimento
    removidos = memoria.decair(HOJE, DIAS_DECAIMENTO_EPISODICA)
    out(f"\nDECAIMENTO  corte {DIAS_DECAIMENTO_EPISODICA} dias: {removidos} episódios removidos, {memoria.contar_episodios()} restam")

    # ---------------------------------------------------------- esquecimento seletivo
    cliente, modelo_llm = cliente_ativo_ou_none()
    agente = None
    if cliente is not None:
        from src.projects.farmacia_precos import config
        from src.projects.farmacia_precos.fabrica import exigir_espelho, montar_agente
        agente, banco, _ = montar_agente()
        exigir_espelho(banco)

    def comportamento(gestor: str) -> str:
        ctx = montar_contexto_memoria(memoria, gestor, PERGUNTA_TESTE)
        no_contexto = ctx.fatos.get(f"usuario:{gestor}:farmacia_padrao", "nenhuma")
        if agente is None:
            return f"farmácia padrão no contexto: {no_contexto} (resposta do agente não executada: sem LLM)"
        exe = executar_com_memoria(agente, memoria, gestor, PERGUNTA_TESTE,
                                   Orcamento(config.max_passos(), config.max_tokens()), PASTA_CHECKPOINTS, HOJE, escrever=False)
        farmacias = sorted({p["argumentos"].get("farmacia", "(todas)") for p in exe.resultado.trajetoria
                            if p.get("tipo") == "chamada_ferramenta"})
        return (f"farmácia padrão no contexto: {no_contexto} | o agente consultou: {farmacias or 'nada'}"
                f" | resposta: {(exe.resultado.resposta_final or '').strip()[:300]}")

    # Demonstrado com o OUTRO gestor, que não tem preferência gravada: assim "voltou" significa
    # voltar ao estado sem memória, e não ao fato anterior de uma contradição.
    out("\nESQUECIMENTO")
    original = comportamento(OUTRO_GESTOR)
    gravado = memoria.gravar_fato(f"usuario:{OUTRO_GESTOR}:farmacia_padrao", "Pacheco", "2026-10-05", "declaração do gestor")
    com_registro = comportamento(OUTRO_GESTOR)
    memoria.remover_registro(gravado.id)
    depois = comportamento(OUTRO_GESTOR)
    out(f"  sem o registro:   {original}")
    out(f"  com o registro:   {com_registro}")
    out(f"  depois da remoção: {depois}")
    out(f"  voltou ao original? {'sim' if depois.split('|')[0] == original.split('|')[0] else 'NÃO'}")
    registro["esquecimento"] = {"original": original, "com_registro": com_registro, "depois": depois}

    # ---------------------------------------------------------- não reprodutibilidade
    out("\nNÃO REPRODUTIBILIDADE")
    if agente is None:
        out(f"  não executado: {modelo_llm}")
    else:
        vazia = Memoria(embeddings, pasta=PASTA_DEMO / "vazia")
        r_vazia = executar_com_memoria(agente, vazia, GESTOR, PERGUNTA_TESTE,
                                       Orcamento(config.max_passos(), config.max_tokens()), PASTA_CHECKPOINTS, HOJE, escrever=False)
        r_cheia = executar_com_memoria(agente, memoria, GESTOR, PERGUNTA_TESTE,
                                       Orcamento(config.max_passos(), config.max_tokens()), PASTA_CHECKPOINTS, HOJE, escrever=False)
        out(f"  execução com memória vazia .... {(r_vazia.resultado.resposta_final or '').strip()}")
        out(f"  execução com memória cheia .... {(r_cheia.resultado.resposta_final or '').strip()}")
        out(f"  (memória cheia: {r_cheia.contexto.tokens} tokens de contexto, fatos {r_cheia.contexto.fatos})")
        registro["nao_reprodutibilidade"] = {
            "vazia": r_vazia.resultado.resposta_final, "cheia": r_cheia.resultado.resposta_final,
            "checkpoint_vazia": str(r_vazia.caminho_checkpoint.relative_to(RAIZ)),
            "checkpoint_cheia": str(r_cheia.caminho_checkpoint.relative_to(RAIZ)),
        }
        vazia.fechar()

    # ---------------------------------------------------------- remoção por titular
    out("\nREMOÇÃO DO TITULAR (cobertura)")
    estruturas = [PASTA_CHECKPOINTS, PASTA_DEMO]
    antes_varredura = memoria.varrer(GESTOR, estruturas)
    relatorio = memoria.remover_titular(GESTOR, [PASTA_CHECKPOINTS])
    depois_varredura = memoria.varrer(GESTOR, estruturas)
    out(f"  achados antes: {len(antes_varredura)} -> removidos por estrutura: {relatorio}")
    out(f"  varredura independente depois: {depois_varredura or 'nenhuma ocorrência de ' + GESTOR}")
    registro["remocao"] = {"antes": antes_varredura, "relatorio": relatorio, "depois": depois_varredura}

    estado = memoria.conn.execute("SELECT COUNT(*) FROM episodica").fetchone()[0], memoria.contar_chaves()
    out("\nCARIMBO")
    out(f"  estado da memória ...... dados/memoria_demo (recriada a cada execução): {estado[0]} episódios, {estado[1]} chaves,"
        f" {contar_tokens(memoria.texto_procedural())} tokens procedurais")
    out(f"  modelo de embedding .... {embeddings.nome}")
    out(f"  decaimento ............. {DIAS_DECAIMENTO_EPISODICA} dias (remoção)   teto de memória na janela: {TETO_TOKENS_MEMORIA} tokens")
    out(f"  modelo do agente ....... {modelo_llm if cliente is not None else 'não executado'}")
    memoria.fechar()

    PASTA_LOG.mkdir(parents=True, exist_ok=True)
    (PASTA_LOG / "memoria.json").write_text(json.dumps(registro, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (PASTA_LOG / "saida.txt").write_text("\n".join(_linhas) + "\n", encoding="utf-8")


if __name__ == "__main__":
    np.set_printoptions(precision=4)
    main()
