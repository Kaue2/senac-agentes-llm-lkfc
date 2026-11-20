"""Visualizador dos traces exportados em JSONL (Parte 3, §4.2: "o README diz como vê-los").

Uso:
  python -m src.observabilidade.ver                       # os 3 últimos traces do arquivo de hoje
  python -m src.observabilidade.ver --arquivo logs/traces/traces-2026-11-20.jsonl --ultimos 10
  python -m src.observabilidade.ver --trace <trace_id>    # um trace, com todos os atributos
  python -m src.observabilidade.ver --thread G-0042:s1    # todos os traces de uma conversa

Imprime a árvore de spans com duração, os atributos `app.*` e `gen_ai.*` da raiz, e os eventos
(aprovação solicitada, aprovação humana, escrita executada).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from .telemetria import PASTA_TRACES

sys.stdout.reconfigure(encoding="utf-8")


def carregar(arquivos: list[Path]) -> dict[str, list[dict]]:
    traces: dict[str, list[dict]] = defaultdict(list)
    for arquivo in arquivos:
        for linha in arquivo.read_text(encoding="utf-8").splitlines():
            if linha.strip():
                s = json.loads(linha)
                traces[s["context"]["trace_id"]].append(s)
    return traces


def _ms(s: dict) -> float:
    ini = datetime.fromisoformat(s["start_time"].replace("Z", "+00:00"))
    fim = datetime.fromisoformat(s["end_time"].replace("Z", "+00:00"))
    return (fim - ini).total_seconds() * 1000


def _raiz(spans: list[dict]) -> dict:
    return next(s for s in spans if not s.get("parent_id"))


def imprimir(spans: list[dict], completo: bool = False) -> None:
    filhos: dict[str | None, list[dict]] = defaultdict(list)
    for s in spans:
        filhos[s.get("parent_id")].append(s)
    raiz = _raiz(spans)
    a = raiz["attributes"]
    print(f"\ntrace {raiz['context']['trace_id']}  {raiz['start_time']}")
    print(f"  versão {a.get('app.versao_sistema')} · {a.get('app.tipo_invocacao')} · thread {a.get('app.thread_id')} "
          f"· turno {a.get('app.turno')} · término {a.get('app.motivo_terminacao')} · suficiência {a.get('app.suficiencia')}")

    def desenhar(s: dict, prefixo: str, ultimo: bool) -> None:
        at = s["attributes"]
        detalhe = ""
        if s["name"].startswith("chat"):
            detalhe = f"etapa={at.get('app.etapa')} in={at.get('gen_ai.usage.input_tokens', '?')} out={at.get('gen_ai.usage.output_tokens', '?')}"
        elif s["name"].startswith("execute_tool"):
            detalhe = f"args={at.get('app.tool.argumentos', '')[:80]}"
            if at.get("app.rag.trechos"):
                detalhe += f" trechos={at['app.rag.trechos']}"
            if at.get("app.tool.erro"):
                detalhe += f" ERRO={at['app.tool.erro'][:60]}"
        status = "" if s["status"]["status_code"] in ("UNSET", "OK") else f" [{s['status']['status_code']}]"
        print(f"{prefixo}{'└── ' if ultimo else '├── '}{s['name']}  {_ms(s):.0f} ms{status}  {detalhe}")
        lista = sorted(filhos.get(s["context"]["span_id"], []), key=lambda x: x["start_time"])
        for i, f in enumerate(lista):
            desenhar(f, prefixo + ("    " if ultimo else "│   "), i == len(lista) - 1)

    print(f"{raiz['name']}  {_ms(raiz):.0f} ms")
    lista = sorted(filhos.get(raiz["context"]["span_id"], []), key=lambda x: x["start_time"])
    for i, f in enumerate(lista):
        desenhar(f, "", i == len(lista) - 1)
    chaves = sorted(a) if completo else [k for k in ("app.entrada", "app.saida", "app.fontes", "app.prompt.agente",
                                                     "app.prompt.triagem", "gen_ai.request.model", "app.checkpoint_id") if k in a]
    for k in chaves:
        print(f"  {k}: {str(a[k])[:300]}")
    for e in raiz.get("events", []):
        print(f"  evento {e['name']} @ {e['timestamp']}: {json.dumps(e.get('attributes', {}), ensure_ascii=False)[:300]}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--arquivo", type=Path, nargs="*", help="Arquivos JSONL (padrão: o de hoje).")
    p.add_argument("--ultimos", type=int, default=3)
    p.add_argument("--trace")
    p.add_argument("--thread")
    args = p.parse_args()
    arquivos = args.arquivo or sorted(PASTA_TRACES.glob("traces-*.jsonl"))[-1:]
    if not arquivos:
        raise SystemExit(f"nenhum arquivo de trace em {PASTA_TRACES}")
    traces = carregar(arquivos)
    ordenados = sorted(traces.values(), key=lambda sp: _raiz(sp)["start_time"])
    if args.trace:
        imprimir(traces[args.trace], completo=True)
    elif args.thread:
        for sp in ordenados:
            if _raiz(sp)["attributes"].get("app.thread_id") == args.thread:
                imprimir(sp)
    else:
        for sp in ordenados[-args.ultimos:]:
            imprimir(sp)


if __name__ == "__main__":
    main()
