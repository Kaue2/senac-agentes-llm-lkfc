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
# Critério acrescentado depois da amostra v1 (que tinha 1 "não" só, e o juiz o errou): sem negativos
# suficientes, a concordância mede só o lado fácil. É uma regra MAIS rígida que a declarada em
# 2026-10-09, e vale para as validações a partir da amostra v2.
MINIMO_NEGATIVOS = 5
RUBRICA_PADRAO = "juiz_fundamentacao_v1"
MARCAS_ROTULADOR_ASSISTENTE = ("assistente de ia", "claude")


def rotulador_e_assistente(rotulador: str) -> bool:
    """Registro de quem rotulou. Não bloqueia a adoção (decisão do grupo, docs/evals.md §3): só faz
    o relatório dizer de onde vieram os rótulos."""
    return any(m in rotulador.casefold() for m in MARCAS_ROTULADOR_ASSISTENTE)


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


def julgar(linhas: list[dict], rubrica: str = RUBRICA_PADRAO, refazer: bool = False) -> list[dict]:
    from dotenv import load_dotenv

    load_dotenv(RAIZ / ".env")
    from src.core.llm_client import ConfiguracaoModelo, criar_cliente
    from src.core.prompts import carregar_prompt
    from src.evals.juiz import JuizFundamentacao

    config = ConfiguracaoModelo.do_ambiente()
    juiz = JuizFundamentacao(criar_cliente(config), config.modelo)
    juiz.prompt = carregar_prompt(rubrica)
    for l in linhas:
        if l["veredito_juiz"] and not refazer:
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
    assistente = any(rotulador_e_assistente(l["rotulador"]) for l in rotuladas)
    m = {f"juiz_{j}_humano_{h}": sum(1 for a, b, _ in pares if a == j and b == h) for j in ("sim", "nao") for h in ("sim", "nao")}
    n = len(pares)
    concordancia = (m["juiz_sim_humano_sim"] + m["juiz_nao_humano_nao"]) / n if n else 0.0
    desacordos = [{"amostra_id": l["amostra_id"], "caso_id": l["caso_id"], "juiz": j, "humano": h,
                   "nota_humana": l["nota_humana"], "justificativa_juiz": l["justificativa_juiz"],
                   "classificacao": l["classificacao_desacordo"] or "PENDENTE"} for j, h, l in pares if j != h]
    return {
        "n_rotuladas": n, "n_amostras": len(linhas), "matriz": m, "concordancia": concordancia,
        "limiar": LIMIAR_ADOCAO, "minimo_rotulos": MINIMO_ROTULOS,
        "rotulos_do_assistente": assistente,
        "negativos": m["juiz_sim_humano_nao"] + m["juiz_nao_humano_nao"],
        "negativos_pegos": m["juiz_nao_humano_nao"],
        "minimo_negativos": MINIMO_NEGATIVOS,
        "adotado": (n >= MINIMO_ROTULOS and concordancia >= LIMIAR_ADOCAO
                    and m["juiz_sim_humano_nao"] + m["juiz_nao_humano_nao"] >= MINIMO_NEGATIVOS
                    and all(d["classificacao"] in CLASSIFICACOES for d in desacordos)),
        "desacordos": desacordos, "rotuladores": sorted({l["rotulador"] for l in rotuladas}),
    }


def caminho_validacao(amostra: Path, rubrica: str) -> Path:
    if amostra == CAMINHO_ROTULOS and rubrica == RUBRICA_PADRAO:
        return CAMINHO_VALIDACAO  # o nome da 1ª validação, já citado nos documentos
    return PASTA / f"validacao_{amostra.stem.replace('rotulos_', '')}_{rubrica}.json"


def resumo_validacao() -> str:
    """A validação que vale para o relatório: a mais recente gravada (vigente.json aponta para ela)."""
    vigente = PASTA / "vigente.json"
    caminho = Path(json.loads(vigente.read_text(encoding="utf-8"))["validacao"]) if vigente.exists() else CAMINHO_VALIDACAO
    caminho = caminho if caminho.is_absolute() else RAIZ / caminho
    if not caminho.exists():
        return "JUIZ não validado   limiar 85%   -> não adotado"
    v = json.loads(caminho.read_text(encoding="utf-8"))
    origem = " (rótulos do assistente de IA)" if v.get("rotulos_do_assistente", v.get("rotulos_humanos") is False) else ""
    return (f"JUIZ rubrica {v.get('rubrica', RUBRICA_PADRAO)}   concordância {100 * v['concordancia']:.0f}% em {v['n_rotuladas']}{origem}"
            f"   negativos pegos {v.get('negativos_pegos', '?')}/{v.get('negativos', '?')}   "
            f"limiar {100 * v['limiar']:.0f}%   -> {'adotado' if v['adotado'] else 'não adotado'}")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser()
    p.add_argument("--preparar", nargs="+", type=Path, metavar="RODADA")
    p.add_argument("--julgar", action="store_true")
    p.add_argument("--matriz", action="store_true")
    p.add_argument("--amostra", type=Path, default=CAMINHO_ROTULOS, help="CSV da amostra (padrão: rotulos_v1.csv).")
    p.add_argument("--rubrica", default=RUBRICA_PADRAO, help="Prompt do juiz em src/prompts/ (padrão: juiz_fundamentacao_v1).")
    p.add_argument("--refazer", action="store_true", help="Com --julgar: julga de novo mesmo as linhas já julgadas.")
    args = p.parse_args()
    if args.preparar:
        if args.amostra.exists() and any(l["rotulo_humano"].strip() for l in ler(args.amostra)):
            raise SystemExit("já há rótulos no CSV: preparar de novo os apagaria.")
        amostra = preparar(args.preparar)
        gravar(amostra, args.amostra)
        print(f"{len(amostra)} amostras em {args.amostra}")
    if args.julgar:
        gravar(julgar(ler(args.amostra), args.rubrica, args.refazer), args.amostra)
    if args.matriz:
        v = matriz(ler(args.amostra))
        v["rubrica"], v["amostra"] = args.rubrica, str(args.amostra)
        destino = caminho_validacao(args.amostra, args.rubrica)
        destino.write_text(json.dumps(v, ensure_ascii=False, indent=2), encoding="utf-8")
        (PASTA / "vigente.json").write_text(json.dumps({"validacao": str(destino.relative_to(RAIZ)) if destino.is_relative_to(RAIZ) else str(destino)}), encoding="utf-8")
        m = v["matriz"]
        print(f"rotuladas {v['n_rotuladas']}/{v['n_amostras']}  rotuladores: {', '.join(v['rotuladores'])}")
        print(f"                humano sim   humano não\n juiz sim    {m['juiz_sim_humano_sim']:>10}   {m['juiz_sim_humano_nao']:>10}"
              f"\n juiz não    {m['juiz_nao_humano_sim']:>10}   {m['juiz_nao_humano_nao']:>10}")
        print(f"concordância {100 * v['concordancia']:.0f}% (limiar {100 * v['limiar']:.0f}%) -> {'ADOTADO' if v['adotado'] else 'NÃO ADOTADO'}")
        print(f"negativos na amostra: {v['negativos']} (mínimo {v['minimo_negativos']}); pegos pelo juiz: {v['negativos_pegos']}")
        if v["rotulos_do_assistente"]:
            print("  rótulos do assistente de IA (declarado em rotulador)")
        for d in v["desacordos"]:
            print(f"  {d['amostra_id']} {d['caso_id']}: juiz={d['juiz']} humano={d['humano']}  [{d['classificacao']}]")


if __name__ == "__main__":
    main()
