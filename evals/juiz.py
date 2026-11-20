"""O juiz da suíte, validado contra rótulos humanos (Parte 3, §1.3).

Propriedade: *a resposta está fundamentada na trajetória* (rubrica `src/prompts/juiz_fundamentacao_v1.md`,
binária, um exemplo de cada lado — Exercício 11, §3). O juiz é o do Exercício 11
(`src/evals/juiz.py::JuizFundamentacao`); aqui está o fluxo de validação sobre saídas da suíte da
Parte 3.

Limiar de adoção: 85% de concordância (`src.evals.juiz.LIMIAR_ADOCAO`), declarado em 2026-10-09,
antes de qualquer medição — mantido. O mínimo de rótulos cai de 30 (Exercício 11) para os 20 que o
enunciado da Parte 3 pede; a mudança está declarada em docs/evals.md §3.

Uso, em três passos:
  python -m evals.juiz --preparar evals/resultados/<rodada-A> evals/resultados/<rodada-B>
      sorteia 20 saídas (estratificadas por classe, semente fixa) para evals/juiz/rotulos_v1.csv,
      com as colunas do rótulo humano VAZIAS
  (uma pessoa do grupo preenche rotulo_humano = sim|nao, nota_humana e rotulador, SEM olhar o
   veredito do juiz — o --julgar pode rodar antes ou depois, mas a coluna do juiz fica à direita)
  python -m evals.juiz --julgar          # preenche veredito_juiz e justificativa_juiz
  python -m evals.juiz --matriz          # matriz juiz × humano, concordância, desacordos, adoção

O juiz NÃO entra na taxa da suíte enquanto não for adotado. Rótulo escrito por modelo não conta
como rótulo humano: o CSV exige `rotulador` preenchido, e a validação recusa rotulador vazio.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
PASTA = RAIZ / "evals" / "juiz"
CAMINHO_ROTULOS = PASTA / "rotulos_v1.csv"
CAMINHO_VALIDACAO = PASTA / "validacao_v1.json"
N_AMOSTRAS = 20
MINIMO_ROTULOS = 20
SEMENTE = 20261120
COLUNAS = ("amostra_id", "rodada", "caso_id", "classe", "pergunta", "resultados_ferramentas", "resposta",
           "rotulo_humano", "nota_humana", "rotulador", "veredito_juiz", "justificativa_juiz", "classificacao_desacordo")
CLASSIFICACOES = ("juiz", "rubrica", "rotulo_humano")


def preparar(rodadas: list[Path]) -> list[dict]:
    from src.evals.juiz import resultados_para_juiz

    candidatos: dict[str, list[dict]] = defaultdict(list)
    for rodada in rodadas:
        for arq in sorted((rodada / "casos").glob("*.json")):
            c = json.loads(arq.read_text(encoding="utf-8"))
            if c["saidas"][-1]["motivo_terminacao"] != "resposta_final":
                continue  # recusa da triagem e pergunta de volta não têm afirmação factual a julgar
            candidatos[c["classe"]].append({
                "rodada": rodada.name, "caso_id": c["id"], "classe": c["classe"], "pergunta": c["entrada"],
                "resultados_ferramentas": resultados_para_juiz(c["trajetoria"]), "resposta": c["saidas"][-1]["resultado"],
            })
    rng = random.Random(SEMENTE)
    for lista in candidatos.values():
        rng.shuffle(lista)
    amostra: list[dict] = []
    while len(amostra) < N_AMOSTRAS and any(candidatos.values()):  # round-robin entre classes
        for classe in sorted(candidatos):
            if candidatos[classe] and len(amostra) < N_AMOSTRAS:
                amostra.append(candidatos[classe].pop())
    for i, linha in enumerate(amostra, start=1):
        linha.update({"amostra_id": f"J{i:02d}", "rotulo_humano": "", "nota_humana": "", "rotulador": "",
                      "veredito_juiz": "", "justificativa_juiz": "", "classificacao_desacordo": ""})
    return amostra


def ler(caminho: Path = CAMINHO_ROTULOS) -> list[dict]:
    if not caminho.exists():
        return []
    with caminho.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def gravar(linhas: list[dict], caminho: Path = CAMINHO_ROTULOS) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUNAS)
        w.writeheader()
        w.writerows({k: l.get(k, "") for k in COLUNAS} for l in linhas)


def julgar(linhas: list[dict]) -> list[dict]:
    from dotenv import load_dotenv

    load_dotenv(RAIZ / ".env")
    from src.core.llm_client import ConfiguracaoModelo, criar_cliente
    from src.evals.juiz import JuizFundamentacao

    config = ConfiguracaoModelo.do_ambiente()
    juiz = JuizFundamentacao(criar_cliente(config), config.modelo)
    for l in linhas:
        if l["veredito_juiz"]:
            continue
        v = juiz.julgar(l["pergunta"], l["resultados_ferramentas"], l["resposta"])
        l["veredito_juiz"] = "" if v.fundamentada is None else ("sim" if v.fundamentada else "nao")
        l["justificativa_juiz"] = v.justificativa or (v.erro or "")
        print(f"{l['amostra_id']} {l['caso_id']:4} juiz={l['veredito_juiz'] or 'ERRO'}")
    return linhas


def matriz(linhas: list[dict]) -> dict:
    from src.evals.juiz import LIMIAR_ADOCAO

    rotuladas = [l for l in linhas if l["rotulo_humano"].strip().lower() in ("sim", "nao", "não")]
    sem_rotulador = [l["amostra_id"] for l in rotuladas if not l["rotulador"].strip()]
    if sem_rotulador:
        raise SystemExit(f"rótulo sem rotulador declarado: {', '.join(sem_rotulador)} — preencha quem rotulou.")
    pares = [(l["veredito_juiz"], "nao" if l["rotulo_humano"].strip().lower() == "não" else l["rotulo_humano"].strip().lower(), l)
             for l in rotuladas if l["veredito_juiz"] in ("sim", "nao")]
    m = {f"juiz_{j}_humano_{h}": sum(1 for a, b, _ in pares if a == j and b == h) for j in ("sim", "nao") for h in ("sim", "nao")}
    n = len(pares)
    concordancia = (m["juiz_sim_humano_sim"] + m["juiz_nao_humano_nao"]) / n if n else 0.0
    desacordos = [{"amostra_id": l["amostra_id"], "caso_id": l["caso_id"], "juiz": j, "humano": h,
                   "nota_humana": l["nota_humana"], "justificativa_juiz": l["justificativa_juiz"],
                   "classificacao": l["classificacao_desacordo"] or "PENDENTE"} for j, h, l in pares if j != h]
    return {
        "n_rotuladas": n, "n_amostras": len(linhas), "matriz": m, "concordancia": concordancia,
        "limiar": LIMIAR_ADOCAO, "minimo_rotulos": MINIMO_ROTULOS,
        "adotado": n >= MINIMO_ROTULOS and concordancia >= LIMIAR_ADOCAO and all(d["classificacao"] in CLASSIFICACOES for d in desacordos),
        "desacordos": desacordos, "rotuladores": sorted({l["rotulador"] for l in rotuladas}),
    }


def resumo_validacao() -> str:
    if not CAMINHO_VALIDACAO.exists():
        n = sum(1 for l in ler() if l["rotulo_humano"].strip())
        return (f"JUIZ rubrica juiz_fundamentacao v1.0   não validado ({n}/{N_AMOSTRAS} rótulos humanos)   "
                "limiar 85%   -> não adotado")
    v = json.loads(CAMINHO_VALIDACAO.read_text(encoding="utf-8"))
    return (f"JUIZ rubrica juiz_fundamentacao v1.0   concordância {100 * v['concordancia']:.0f}% em {v['n_rotuladas']}   "
            f"limiar {100 * v['limiar']:.0f}%   -> {'adotado' if v['adotado'] else 'não adotado'}")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser()
    p.add_argument("--preparar", nargs="+", type=Path, metavar="RODADA")
    p.add_argument("--julgar", action="store_true")
    p.add_argument("--matriz", action="store_true")
    args = p.parse_args()
    if args.preparar:
        if CAMINHO_ROTULOS.exists() and any(l["rotulo_humano"].strip() for l in ler()):
            raise SystemExit("já há rótulos humanos no CSV: preparar de novo os apagaria.")
        amostra = preparar(args.preparar)
        gravar(amostra)
        print(f"{len(amostra)} amostras em {CAMINHO_ROTULOS.relative_to(RAIZ)}")
    if args.julgar:
        gravar(julgar(ler()))
    if args.matriz:
        v = matriz(ler())
        CAMINHO_VALIDACAO.write_text(json.dumps(v, ensure_ascii=False, indent=2), encoding="utf-8")
        m = v["matriz"]
        print(f"rotuladas {v['n_rotuladas']}/{v['n_amostras']}  rotuladores: {', '.join(v['rotuladores'])}")
        print(f"                humano sim   humano não\n juiz sim    {m['juiz_sim_humano_sim']:>10}   {m['juiz_sim_humano_nao']:>10}"
              f"\n juiz não    {m['juiz_nao_humano_sim']:>10}   {m['juiz_nao_humano_nao']:>10}")
        print(f"concordância {100 * v['concordancia']:.0f}% (limiar {100 * v['limiar']:.0f}%) -> {'ADOTADO' if v['adotado'] else 'NÃO ADOTADO'}")
        for d in v["desacordos"]:
            print(f"  {d['amostra_id']} {d['caso_id']}: juiz={d['juiz']} humano={d['humano']}  [{d['classificacao']}]")


if __name__ == "__main__":
    main()
