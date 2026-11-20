"""Compara duas rodadas da suíte (Parte 3, §1.4) e aplica a regra de promoção do Exercício 11.

Uso:
  python -m evals.comparar evals/resultados/<rodada-A> evals/resultados/<rodada-B> [--ruido-pp 4.0]

`--ruido-pp` é o ruído de base em pontos percentuais (diferença entre duas rodadas completas da
versão A). Sem ele, a regra usa só o piso de 5 p.p. e a saída diz que o ruído não foi medido.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.evals import regra

from .juiz import resumo_validacao


def carregar(pasta: Path) -> tuple[dict, dict[str, dict]]:
    """A pontuação de uma rodada: a de `reavaliacao.json` se houver (régua atual), senão a original.
    O dataset de cada uma vai junto, para a comparação recusar réguas diferentes."""
    resumo = json.loads((pasta / "resumo.json").read_text(encoding="utf-8"))
    reav = pasta / "reavaliacao.json"
    if reav.exists():
        r = json.loads(reav.read_text(encoding="utf-8"))
        resumo = {**resumo, "dataset_pontuacao": r["dataset"], "pontuacao": "reavaliada", "avaliador_commit": r["avaliador_commit"]}
        return resumo, r["casos"]
    casos = {}
    for p in (pasta / "casos").glob("*.json"):
        c = json.loads(p.read_text(encoding="utf-8"))
        casos[c["id"]] = c
    return {**resumo, "dataset_pontuacao": resumo["carimbo"]["dataset"], "pontuacao": "original"}, casos


def comparar(pasta_a: Path, pasta_b: Path, ruido_pp: float | None) -> str:
    ra, ca = carregar(pasta_a)
    rb, cb = carregar(pasta_b)
    if ra["dataset_pontuacao"] != rb["dataset_pontuacao"]:
        raise SystemExit(f"réguas diferentes: A pontuada em {ra['dataset_pontuacao']}, B em {rb['dataset_pontuacao']}. "
                         "Rode python -m evals.reavaliar nas duas rodadas antes de comparar.")
    comuns = sorted(set(ca) & set(cb))
    linhas = []
    d = ra["carimbo"]["dataset_resumo"]
    origem = d["por_origem"]
    linhas.append(f"DATASET {ra['dataset_pontuacao'].split(' ')[1]}   {len(comuns)} casos em comum   "
                  f"(producao {origem.get('producao', 0)} · desenvolvimento {origem.get('desenvolvimento', 0)} · sintetico {origem.get('sintetico', 0)})")
    linhas.append(resumo_validacao())
    linhas.append(f"A = {pasta_a.name} (sistema {ra['carimbo']['versao_sistema']}, commit {ra['carimbo']['commit']}, pontuação {ra['pontuacao']})")
    linhas.append(f"B = {pasta_b.name} (sistema {rb['carimbo']['versao_sistema']}, commit {rb['carimbo']['commit']}, pontuação {rb['pontuacao']})")
    linhas.append("")

    def taxa(casos: dict, ids: list[str]) -> float:
        return sum(casos[i]["passou"] for i in ids) / len(ids) if ids else 0.0

    classes = sorted({ca[i]["classe"] for i in comuns})
    linhas.append(f"{'classe':<18}{'versão A':>10}{'versão B':>10}{'delta':>9}")
    taxas_a, taxas_b = {}, {}
    for c in classes:
        ids = [i for i in comuns if ca[i]["classe"] == c]
        taxas_a[c], taxas_b[c] = taxa(ca, ids), taxa(cb, ids)
        linhas.append(f"{c:<18}{100 * taxas_a[c]:>9.0f}%{100 * taxas_b[c]:>9.0f}%{100 * (taxas_b[c] - taxas_a[c]):>+8.0f}")
    ta, tb = taxa(ca, comuns), taxa(cb, comuns)
    linhas.append(f"{'MÉDIA':<18}{100 * ta:>9.1f}%{100 * tb:>9.1f}%{100 * (tb - ta):>+8.1f}")

    linhas.append("")
    mudou = [(i, ca[i]["passou"], cb[i]["passou"]) for i in comuns if ca[i]["passou"] != cb[i]["passou"]]
    linhas.append("casos que mudaram:" if mudou else "nenhum caso mudou de resultado")
    for i, a, b in mudou:
        linhas.append(f"  {i} ({ca[i]['classe']}): {'passou' if a else 'falhou'} -> {'passou' if b else 'falhou'}"
                      + (f"   B falhou em: {', '.join(cb[i]['falhas'])}" if not b else f"   A falhou em: {', '.join(ca[i]['falhas'])}"))

    criticas = {c: all(cb[i]["passou"] for i in comuns if cb[i]["classe"] == c) for c in regra.CLASSES_CRITICAS if c in classes}
    decisao = regra.aplicar(ta, tb, ruido_pp or 0.0, taxas_a, taxas_b, criticas)
    linhas.append("")
    linhas.append(f"REGRA DE PROMOÇÃO v{regra.VERSAO_REGRA} (declarada em {regra.DECLARADA_EM}); ruído de base: "
                  + (f"{ruido_pp:.1f} p.p." if ruido_pp is not None else "NÃO MEDIDO (usado só o piso)"))
    linhas += [f"  {m}" for m in decisao.motivos]
    linhas.append(f"  -> {'PROMOVER B' if decisao.promover else 'NÃO PROMOVER B'}"
                  "  (1 repetição por versão: o pass^k da condição 3 é pass^1)")
    return "\n".join(linhas)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser()
    p.add_argument("rodada_a", type=Path)
    p.add_argument("rodada_b", type=Path)
    p.add_argument("--ruido-pp", type=float, default=None)
    p.add_argument("--gravar", type=Path, help="Também grava o relatório neste arquivo.")
    args = p.parse_args()
    texto = comparar(args.rodada_a, args.rodada_b, args.ruido_pp)
    print(texto)
    if args.gravar:
        args.gravar.write_text(texto + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
