"""Exercício 6 (complementar) — o buscador da base de conhecimento do case.

Uso:
    python scripts/aula06_buscador.py                     # relatório da configuração escolhida
    python scripts/aula06_buscador.py --comparar-modelos  # + desafio A (três modelos locais)

Mede as três estratégias de corte com recall@k sobre dados/avaliacao/perguntas_rag_v1.jsonl,
calibra o limiar do portão, diagnostica a pergunta que falha e, se houver LLM no .env, mostra o
que acontece com uma pergunta sem resposta com o portão desligado. Grava tudo em
logs/aula06/buscador.json e o índice escolhido em dados/indices/estrutura.db.

Parâmetros e justificativas:
- `KS = (3, 5)`: o enunciado pede ao menos dois valores de k; k=1 também é reportado porque é o
  que mostra a cegueira de tempo (política 2026 e 2025 disputando a primeira posição).
- `K_ESCOLHIDO` e `ESTRATEGIA_ESCOLHIDA`: decididos pelos números deste script (ver relatório).
- `LIMIARES`: varredura de 0,05 a 0,30 em passos de 0,0005. O e5-large concentra as distâncias
  numa faixa estreita (~0,08 a ~0,22), e um passo de 0,01 pularia a janela que separa as
  perguntas com e sem resposta.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()

import tiktoken  # noqa: E402

from src.core.llm_client import cliente_ativo_ou_none  # noqa: E402
from src.rag.avaliacao import (  # noqa: E402
    carregar_perguntas,
    escolher_limiar,
    evidencia_intacta_no_indice,
    posicao_da_evidencia,
    recall_at_k,
    trecho_contem_evidencia,
    varrer_limiares,
)
from src.rag.chunking import ESTRATEGIAS, SOBREPOSICAO, TAMANHO_CARACTERES, cortar_corpus  # noqa: E402
from src.rag.corpus import carregar_corpus  # noqa: E402
from src.rag.embeddings import EmbeddingComCache, EmbeddingLocal, modelo_do_ambiente  # noqa: E402
from src.rag.indice import IndiceVetorial  # noqa: E402
from src.rag.resposta import PipelineRAG  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]
PASTA_LOG = RAIZ / "logs" / "aula06"
KS = (1, 3, 5)
K_ESCOLHIDO = 3
ESTRATEGIA_ESCOLHIDA = "estrutura"
LIMIARES = [round(0.05 + 0.0005 * i, 4) for i in range(501)]
MODELOS_DESAFIO_A = (
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    "sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
    "intfloat/multilingual-e5-large",
)

# Diagnóstico da pergunta que falha. O script detecta sozinho o defeito de CHUNKING (a evidência
# não existe inteira em nenhum trecho do índice). Para separar "pergunta mal feita" de
# "limitação do vetor", o teste é reformular: se a mesma intenção, dita com o vocabulário do
# documento, recupera o trecho certo, o vetor representa o conceito e falhou na forma da
# pergunta. Qual dos dois é decisão humana — registrada aqui e conferida a cada execução.
REFORMULACOES = {
    "Q15": {
        "reformulacoes": [
            "Dá para calcular a margem de uma farmácia concorrente?",
            "Qual a margem bruta da farmácia Pague Menos?",
        ],
        "diagnostico": "limitacao do vetor (entidade)",
        "explicacao": (
            "O documento fala em 'farmácia concorrente'; a pergunta nomeia a Pague Menos e o Ozempic. "
            "O vetor não sabe que Pague Menos é uma concorrente: com 'concorrente' na pergunta o trecho "
            "certo vem em 1º; com 'Pague Menos' continua fora do top-k. A pergunta não está mal feita — "
            "é assim que o gestor pergunta. Correção: mapear as 13 redes monitoradas para o conceito "
            "'concorrente' antes da busca (expansão de consulta por cadastro, não por similaridade)."
        ),
    },
}


def contar_tokens(textos: list[str]) -> int:
    codificador = tiktoken.get_encoding("o200k_base")  # família de tokenizador do gpt-oss
    return sum(len(codificador.encode(t)) for t in textos)


def medir_estrategia(docs, perguntas, modelo, estrategia):
    trechos = cortar_corpus(docs, estrategia)
    indice = IndiceVetorial.construir(trechos, modelo, estrategia)
    vetores = modelo.embed_consultas([p.pergunta for p in perguntas])
    posicoes, menor_distancia, top = {}, {}, {}
    for p, v in zip(perguntas, vetores):
        resultados = indice.buscar(v, len(trechos))
        menor_distancia[p.id] = resultados[0].distancia
        top[p.id] = resultados[:5]
        if p.tem_resposta:
            posicoes[p.id] = posicao_da_evidencia(resultados, p)
    return {
        "indice": indice,
        "trechos": trechos,
        "posicoes": posicoes,
        "menor_distancia": menor_distancia,
        "top": top,
        "recall": {k: recall_at_k(posicoes, k) for k in KS},
    }


def pct(x: float) -> str:
    return f"{100 * x:5.1f}%"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--comparar-modelos", action="store_true", help="desafio A: três modelos de embedding")
    args = parser.parse_args()

    docs = carregar_corpus()
    perguntas = carregar_perguntas()
    modelo = modelo_do_ambiente()
    com = [p for p in perguntas if p.tem_resposta]
    sem = [p for p in perguntas if not p.tem_resposta]
    registro: dict = {"executado_em": datetime.now(timezone.utc).isoformat(timespec="seconds")}

    print(f"CORPUS: {len(docs)} documentos, {contar_tokens([d.corpo for d in docs])} tokens (o200k_base)")
    print(f"\nCONJUNTO: {len(perguntas)} perguntas")
    print(f"  com exceção: {sum(p.tipo == 'excecao' for p in perguntas)}   sem resposta no corpus: {len(sem)}")

    medidas = {e: medir_estrategia(docs, perguntas, modelo, e) for e in ESTRATEGIAS}
    print(f"\nRECALL@k  ({len(com)} perguntas com resposta; modelo {modelo.nome})")
    tamanho_corpus = sum(len(d.corpo) for d in docs)
    for m in medidas.values():
        media = sum(len(t.texto) for t in m["trechos"]) / len(m["trechos"])
        m["fracao_corpus_k"] = min(1.0, K_ESCOLHIDO * media / tamanho_corpus)
    print(f"  {'estratégia':22s}{'trechos':>8s}" + "".join(f"{'k=' + str(k):>9s}" for k in KS)
          + f"{'corpus na janela (k=' + str(K_ESCOLHIDO) + ')':>28s}")
    for e, m in medidas.items():
        print(f"  {e:22s}{len(m['trechos']):8d}" + "".join(f"{pct(m['recall'][k]):>9s}" for k in KS)
              + f"{pct(m['fracao_corpus_k']):>28s}")
    escolhida = medidas[ESTRATEGIA_ESCOLHIDA]
    melhor_k = max(medidas, key=lambda e: medidas[e]["recall"][K_ESCOLHIDO])
    print(
        f"  ESCOLHIDA: {ESTRATEGIA_ESCOLHIDA}   k={K_ESCOLHIDO}   porque tem o maior recall@1 "
        f"({pct(escolhida['recall'][1]).strip()}) e põe {pct(escolhida['fracao_corpus_k']).strip()} do corpus "
        f"na janela, contra {pct(medidas[melhor_k]['fracao_corpus_k']).strip()} de '{melhor_k}' "
        f"(recall@{K_ESCOLHIDO} {pct(medidas[melhor_k]['recall'][K_ESCOLHIDO]).strip()}), cujo recall vem de "
        "blocos que misturam de 3 a 6 seções cada; k=5 não recupera nenhuma pergunta a mais"
    )
    registro["recall"] = {
        e: {"n_trechos": len(m["trechos"]), "recall": m["recall"], "posicoes": m["posicoes"],
            "fracao_corpus_na_janela": m["fracao_corpus_k"]} for e, m in medidas.items()
    }

    # ------------------------------------------------------------------ portão
    pontos = varrer_limiares(escolhida["menor_distancia"], perguntas, LIMIARES)
    ponto = escolher_limiar(pontos)
    maior_com = max(escolhida["menor_distancia"][p.id] for p in com)
    menor_sem = min(escolhida["menor_distancia"][p.id] for p in sem)
    print("\nPORTÃO  (distância 1 - cosseno do trecho mais próximo)")
    print(f"  maior distância entre as COM resposta: {maior_com:.4f}")
    print(f"  menor distância entre as SEM resposta: {menor_sem:.4f}   folga: {menor_sem - maior_com:+.4f}")
    if ponto is None:
        print("  nenhum limiar barra uma pergunta sem resposta sem barrar alguma com resposta")
    else:
        print(f"  limiar escolhido: {ponto.limiar:.4f} de distância")
        print(f"  barra {ponto.barradas_sem_resposta}/{ponto.total_sem_resposta} das perguntas sem resposta")
        print(f"  barra {ponto.barradas_com_resposta}/{ponto.total_com_resposta} das perguntas com resposta   <- tem que ser 0")
    for p in sem:
        print(f"    {p.id} distância {escolhida['menor_distancia'][p.id]:.4f}  {p.pergunta}")
    registro["portao"] = {
        "limiar": ponto.limiar if ponto else None,
        "barradas_sem_resposta": ponto.barradas_sem_resposta if ponto else None,
        "barradas_com_resposta": ponto.barradas_com_resposta if ponto else None,
        "maior_distancia_com_resposta": maior_com,
        "menor_distancia_sem_resposta": menor_sem,
        "menor_distancia_por_pergunta": escolhida["menor_distancia"],
        "curva": [p.__dict__ for p in pontos if 0.14 <= p.limiar <= 0.24],
    }

    # ------------------------------------------------------- a pergunta que falha
    print("\nA PERGUNTA QUE FALHA")
    falhas = [p for p in com if (escolhida["posicoes"][p.id] or 99) > K_ESCOLHIDO]
    registro["falhas"] = []
    for p in falhas:
        recuperados = escolhida["top"][p.id][:K_ESCOLHIDO]
        print(f"  {p.id} {p.pergunta}")
        print(f"  esperado: «{p.evidencias[0]}» (posição {escolhida['posicoes'][p.id]})")
        print(f"  recuperado: {', '.join(f'{r.trecho.id} ({r.distancia:.4f})' for r in recuperados)}")
        if not evidencia_intacta_no_indice(escolhida["trechos"], p):
            diagnostico, testes = "chunking (evidência partida entre trechos)", []
        else:
            info = REFORMULACOES.get(p.id, {"reformulacoes": [], "diagnostico": "a diagnosticar", "explicacao": ""})
            testes = []
            for q in info["reformulacoes"]:
                v = modelo.embed_consultas([q])[0]
                pos = posicao_da_evidencia(escolhida["indice"].buscar(v, len(escolhida["trechos"])), p)
                testes.append({"reformulacao": q, "posicao_da_evidencia": pos})
                print(f"    reformulada: «{q}» -> evidência na posição {pos}")
            diagnostico = info["diagnostico"]
            if info["explicacao"]:
                print(f"    {info['explicacao']}")
        print(f"  DIAGNÓSTICO: {diagnostico}")
        registro["falhas"].append(
            {"id": p.id, "posicao": escolhida["posicoes"][p.id], "recuperados": [r.trecho.id for r in recuperados],
             "testes": testes, "diagnostico": diagnostico}
        )

    # ----------------------------- desafio B: o mais similar não é o que responde
    print("\nSIMILARIDADE ≠ RELEVÂNCIA (desafio B)")
    registro["similar_nao_relevante"] = []
    for p in com:
        primeiro = escolhida["top"][p.id][0]
        if not trecho_contem_evidencia(primeiro.trecho, p):
            print(f"  {p.id} 1º lugar: {primeiro.trecho.id} ({primeiro.distancia:.4f}) — evidência na posição "
                  f"{escolhida['posicoes'][p.id]}")
            registro["similar_nao_relevante"].append(
                {"id": p.id, "primeiro": primeiro.trecho.id, "posicao_evidencia": escolhida["posicoes"][p.id]}
            )

    # ------------------------------------------------- índice escolhido, salvo
    caminho_indice = RAIZ / "dados" / "indices" / f"{ESTRATEGIA_ESCOLHIDA}.db"
    escolhida["indice"].salvar(caminho_indice)

    # ------------------------------------------------ portão desligado (com LLM)
    print("\nPORTÃO DESLIGADO — pergunta sem resposta")
    cliente, modelo_llm = cliente_ativo_ou_none()
    if cliente is None or ponto is None:
        print(f"  não executado: {modelo_llm if cliente is None else 'sem limiar calibrado'}")
        registro["portao_desligado"] = {"executado": False}
    else:
        pipeline = PipelineRAG(escolhida["indice"], modelo, cliente, modelo_llm, k=K_ESCOLHIDO, limiar=ponto.limiar)
        registro["portao_desligado"] = {"executado": True, "casos": []}
        for p in sem:
            desligado = pipeline.responder(p.pergunta, portao=False)
            ligado = pipeline.responder(p.pergunta, portao=True)
            print(f"  {p.id} {p.pergunta}")
            print(f"    desligado -> recusou={desligado.recusou}  {desligado.resposta}")
            print(f"    ligado    -> {ligado.resposta}")
            registro["portao_desligado"]["casos"].append(
                {"id": p.id, "desligado": desligado.resposta, "desligado_recusou": desligado.recusou,
                 "desligado_trace": desligado.trace, "ligado": ligado.resposta}
            )

    # ------------------------------------------------------------ desafio A
    if args.comparar_modelos:
        print("\nDESAFIO A — modelos de embedding (mesmas 20 perguntas)")
        print(f"  {'modelo':40s}{'estratégia':20s}{'r@1':>7s}{'r@3':>7s}{'r@5':>7s}{'folga portão':>14s}")
        registro["desafio_a"] = []
        for nome in MODELOS_DESAFIO_A:
            m = EmbeddingComCache(EmbeddingLocal(nome))
            for e in ESTRATEGIAS:
                r = medir_estrategia(docs, perguntas, m, e)
                folga = min(r["menor_distancia"][p.id] for p in sem) - max(r["menor_distancia"][p.id] for p in com)
                print(f"  {nome.split('/')[1]:40s}{e:20s}{pct(r['recall'][1]):>7s}{pct(r['recall'][3]):>7s}"
                      f"{pct(r['recall'][5]):>7s}{folga:+14.4f}")
                registro["desafio_a"].append({"modelo": nome, "estrategia": e, "recall": r["recall"], "folga": folga})

    carimbo = {
        "modelo de embedding": modelo.nome,
        "chunking": f"{ESTRATEGIA_ESCOLHIDA} (seção ##, herda título; alternativas medidas: "
        f"{TAMANHO_CARACTERES} caracteres, {TAMANHO_CARACTERES}+{SOBREPOSICAO} de overlap)",
        "métrica": escolhida["indice"].carimbo["metrica"],
        "k": str(K_ESCOLHIDO),
        "limiar do portão": f"{ponto.limiar:.4f}" if ponto else "não calibrado",
        "conjunto de perguntas": "dados/avaliacao/perguntas_rag_v1.jsonl (v1)",
    }
    print("\nCARIMBO")
    for chave, valor in carimbo.items():
        print(f"  {chave} {'.' * max(2, 22 - len(chave))} {valor}")
    registro["carimbo"] = carimbo

    PASTA_LOG.mkdir(parents=True, exist_ok=True)
    (PASTA_LOG / "buscador.json").write_text(
        json.dumps(registro, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(f"\n[índice salvo em {caminho_indice.relative_to(RAIZ)}; log em logs/aula06/buscador.json]")


if __name__ == "__main__":
    main()
