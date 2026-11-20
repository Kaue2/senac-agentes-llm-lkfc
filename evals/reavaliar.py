"""Pontua de novo uma rodada a partir do que ela GRAVOU, com o avaliador e o dataset atuais — sem
rodar o sistema de novo (Parte 3, docs/evals.md §4).

Uso: python -m evals.reavaliar evals/resultados/<rodada>

Existe porque a leitura da rodada A achou defeitos no INSTRUMENTO (avaliador e uma expectativa do
dataset), e não no sistema. Rodar A de novo trocaria as respostas do modelo; pontuar de novo o que
A respondeu troca só a régua. O `resumo.json` original fica como está; o resultado vai para
`reavaliacao.json`, com a versão do dataset e o commit do avaliador.

O que é recalculado: determinístico, contrato, trajetória, resultado e `aprovacao_fundamentada`
(saem do que o caso gravou: saídas, trajetória, pausas, exportações). O que é CARREGADO da rodada
original, porque dependia de coisas que o caso não grava (o que foi enviado ao modelo, o trace,
o checkpoint e a memória daquele momento): as demais propriedades de segurança.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

from . import avaliar, dataset

_RECALCULADAS_DE_SEGURANCA = ("aprovacao_fundamentada",)


def reavaliar(pasta: Path) -> dict:
    from src.grafo.execucao import commit_atual

    casos_ds = {c.id: c for c in dataset.carregar()}
    por_caso, por_classe, mudaram = {}, defaultdict(list), []
    for arq in sorted((pasta / "casos").glob("*.json")):
        c = json.loads(arq.read_text(encoding="utf-8"))
        caso = casos_ds.get(c["id"])
        if caso is None:
            continue
        esp = caso.esperado
        niveis = {
            "deterministico": avaliar.avaliadores.deterministico(c["saidas"][-1]["resultado"], esp),
            "contrato": avaliar.contrato(c["saidas"], esp),
            "trajetoria": avaliar.avaliadores.trajetoria(c["trajetoria"], esp),
            "resultado": avaliar.resultado(c["exportacoes"], esp, c["saidas"][-1]["motivo_terminacao"], c["ja_existia"]),
            "seguranca": {k: v for k, v in c["niveis"].get("seguranca", {}).items() if k not in _RECALCULADAS_DE_SEGURANCA},
        }
        if esp.get("aprovacao_fundamentada") or c["pausas"]:
            niveis["seguranca"]["aprovacao_fundamentada"] = avaliar.seguranca(esp, c["pausas"], c["trajetoria"], "", {}, "")["aprovacao_fundamentada"]
        passou = avaliar.passou(niveis)
        por_caso[c["id"]] = {"classe": caso.classe, "passou": passou, "falhas": avaliar.falhas(niveis), "niveis": niveis,
                             "passou_original": c["passou"], "falhas_original": c["falhas"]}
        por_classe[caso.classe].append(passou)
        if passou != c["passou"]:
            mudaram.append(c["id"])
    n = len(por_caso)
    return {
        "dataset": f"golden_v2 v{dataset.VERSAO} sha256:{dataset.hash_arquivo()}",
        "avaliador_commit": commit_atual(),
        "n_casos": n,
        "taxa": sum(v["passou"] for v in por_caso.values()) / n if n else 0.0,
        "por_classe": {k: {"n": len(v), "passou": sum(v), "taxa": sum(v) / len(v)} for k, v in sorted(por_classe.items())},
        "mudaram_com_a_reavaliacao": mudaram,
        "casos": por_caso,
    }


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    pasta = Path(sys.argv[1])
    r = reavaliar(pasta)
    (pasta / "reavaliacao.json").write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
    original = json.loads((pasta / "resumo.json").read_text(encoding="utf-8"))
    print(f"{pasta.name}: original {100 * original['taxa']:.1f}% ({original['carimbo']['dataset']}) -> "
          f"reavaliada {100 * r['taxa']:.1f}% ({r['dataset']}, {r['n_casos']} casos)")
    for cid in r["mudaram_com_a_reavaliacao"]:
        v = r["casos"][cid]
        print(f"  {cid}: {'falhou' if not v['passou_original'] else 'passou'} -> {'passou' if v['passou'] else 'falhou'}"
              f"   antes: {', '.join(v['falhas_original']) or '—'}   agora: {', '.join(v['falhas']) or '—'}")


if __name__ == "__main__":
    main()
