"""As métricas da Parte 3 (§4.3) e o SLO de qualidade (§4.4), calculados SÓ dos traces.

Uso:
  python -m src.observabilidade.metricas evals/resultados/<rodada-A>/traces.jsonl evals/resultados/<rodada-B>/traces.jsonl
  python -m src.observabilidade.metricas <arquivos...> --json saida.json

Unidade: uma EXECUÇÃO é uma invocação do grafo — um span raiz `invoke_agent` (um turno, ou a
retomada de uma pausa). Todo número sai com corte por `app.versao_sistema`: um número que mistura
versões soma sistemas diferentes.

| Métrica | De onde sai |
|---|---|
| latência p50/p95 | duração do span raiz |
| custo por execução | soma de `gen_ai.usage.input_tokens`/`output_tokens` dos spans `chat` do trace × preço de referência |
| motivos de término | `app.motivo_terminacao` da raiz |
| taxa de erro por ferramenta | spans `execute_tool` com status ERROR ÷ total da ferramenta |
| SLI de qualidade | ver `TERMINOS_BONS` abaixo |

Preço de referência (tier pago da Groq, openai/gpt-oss-120b, console.groq.com/docs/models,
consultado em 2026-11-20): US$ 0,15 por milhão de tokens de entrada e US$ 0,60 de saída;
câmbio de referência R$ 5,40. O sistema roda no tier gratuito (custo efetivo R$ 0); o valor é o
que custaria fora dele. `PRECO_ENTRADA_USD_M`, `PRECO_SAIDA_USD_M` e `CAMBIO_BRL` trocam os três.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

# SLI de qualidade: fração das execuções VÁLIDAS que terminaram BEM. Bom = o sistema terminou pelo
# caminho que o desenho prevê: respondeu, perguntou o que faltava, recusou o fora do escopo, parou
# para aprovação, ou a aprovação expirou como declarado. Ruim = a degradação silenciosa (orçamento,
# laço, resposta vazia) e o erro (provedor, recursão). Inválida (fora do denominador): entrada vazia
# ou longa — o sistema nem chegou a decidir.
TERMINOS_BONS = {"resposta_final", "esclarecimento_pedido", "fora_do_escopo", "recorte_insuficiente",
                 "pausado_aguardando_humano", "aprovacao_expirada"}
TERMINOS_INVALIDOS = {"entrada_vazia", "entrada_longa"}
SLO_OBJETIVO = 0.95
SLO_JANELA = "7 dias"


def _preco() -> tuple[float, float, float]:
    return (float(os.environ.get("PRECO_ENTRADA_USD_M", "0.15")), float(os.environ.get("PRECO_SAIDA_USD_M", "0.60")),
            float(os.environ.get("CAMBIO_BRL", "5.40")))


def _ms(s: dict) -> float:
    ini = datetime.fromisoformat(s["start_time"].replace("Z", "+00:00"))
    fim = datetime.fromisoformat(s["end_time"].replace("Z", "+00:00"))
    return (fim - ini).total_seconds() * 1000


def percentil(valores: list[float], p: float) -> float:
    """Percentil pelo método do posto mais próximo (sem interpolação): o p95 é um valor que de fato
    ocorreu."""
    if not valores:
        return float("nan")
    ordenados = sorted(valores)
    return ordenados[max(0, math.ceil(p / 100 * len(ordenados)) - 1)]


def carregar(arquivos: list[Path]) -> dict[str, list[dict]]:
    traces: dict[str, list[dict]] = defaultdict(list)
    for a in arquivos:
        for linha in a.read_text(encoding="utf-8").splitlines():
            if linha.strip():
                s = json.loads(linha)
                traces[s["context"]["trace_id"]].append(s)
    return traces


def calcular(arquivos: list[Path]) -> dict[str, dict]:
    pe, ps, cambio = _preco()
    por_versao: dict[str, dict] = defaultdict(lambda: {"latencias": [], "custos": [], "terminos": Counter(),
                                                        "ferramentas": defaultdict(lambda: [0, 0]), "tokens_in": 0, "tokens_out": 0})
    for spans in carregar(arquivos).values():
        raiz = next((s for s in spans if not s.get("parent_id")), None)
        if raiz is None or not raiz["name"].startswith("invoke_agent"):
            continue
        v = por_versao[raiz["attributes"].get("app.versao_sistema", "?")]
        v["latencias"].append(_ms(raiz))
        v["terminos"][raiz["attributes"].get("app.motivo_terminacao", "?")] += 1
        tin = sum(s["attributes"].get("gen_ai.usage.input_tokens", 0) for s in spans if s["name"].startswith("chat "))
        tout = sum(s["attributes"].get("gen_ai.usage.output_tokens", 0) for s in spans if s["name"].startswith("chat "))
        v["tokens_in"] += tin
        v["tokens_out"] += tout
        v["custos"].append((tin * pe + tout * ps) / 1e6 * cambio)
        for s in spans:
            if s["name"].startswith("execute_tool "):
                contagem = v["ferramentas"][s["attributes"].get("gen_ai.tool.name", "?")]
                contagem[0] += 1
                contagem[1] += s["status"]["status_code"] == "ERROR"
    saida = {}
    for versao, v in sorted(por_versao.items()):
        n = len(v["latencias"])
        validas = n - sum(c for t, c in v["terminos"].items() if t in TERMINOS_INVALIDOS)
        boas = sum(c for t, c in v["terminos"].items() if t in TERMINOS_BONS)
        sli = boas / validas if validas else float("nan")
        orcamento = 1 - SLO_OBJETIVO
        saida[versao] = {
            "execucoes": n,
            "latencia_p50_ms": round(percentil(v["latencias"], 50)),
            "latencia_p95_ms": round(percentil(v["latencias"], 95)),
            "custo_medio_brl": round(sum(v["custos"]) / n, 5) if n else 0.0,
            "custo_p95_brl": round(percentil(v["custos"], 95), 5) if n else 0.0,
            "tokens_entrada": v["tokens_in"], "tokens_saida": v["tokens_out"],
            "terminos": dict(v["terminos"].most_common()),
            "erro_por_ferramenta": {f: {"chamadas": t, "erros": e, "taxa": round(e / t, 3)} for f, (t, e) in sorted(v["ferramentas"].items())},
            "slo": {"sli": round(sli, 4), "boas": boas, "validas": validas, "objetivo": SLO_OBJETIVO, "janela": SLO_JANELA,
                    "orcamento_de_erro_consumido": round((1 - sli) / orcamento, 2) if validas else None,
                    "violado": sli < SLO_OBJETIVO},
        }
    return saida


def imprimir(resultado: dict[str, dict]) -> None:
    pe, ps, cambio = _preco()
    print(f"preço de referência: US$ {pe}/M entrada, US$ {ps}/M saída, câmbio R$ {cambio} (custo efetivo no tier gratuito: R$ 0)")
    for versao, m in resultado.items():
        print(f"\n== versão {versao}: {m['execucoes']} execuções")
        print(f"latência p50 {m['latencia_p50_ms']} ms · p95 {m['latencia_p95_ms']} ms")
        print(f"custo por execução: médio R$ {m['custo_medio_brl']:.4f} · p95 R$ {m['custo_p95_brl']:.4f} "
              f"({m['tokens_entrada']} tokens de entrada, {m['tokens_saida']} de saída no total)")
        print("términos: " + ", ".join(f"{t} {c}" for t, c in m["terminos"].items()))
        print("erro por ferramenta: " + ", ".join(f"{f} {e['erros']}/{e['chamadas']}" for f, e in m["erro_por_ferramenta"].items()))
        s = m["slo"]
        print(f"SLO qualidade: SLI {100 * s['sli']:.1f}% ({s['boas']}/{s['validas']}) · objetivo ≥{100 * s['objetivo']:.0f}% em {s['janela']} · "
              f"orçamento de erro consumido {100 * (s['orcamento_de_erro_consumido'] or 0):.0f}% · {'VIOLADO' if s['violado'] else 'cumprido'}")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser()
    p.add_argument("arquivos", nargs="+", type=Path)
    p.add_argument("--json", type=Path)
    args = p.parse_args()
    r = calcular(args.arquivos)
    imprimir(r)
    if args.json:
        args.json.write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
