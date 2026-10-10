"""Validação do juiz (Exercício 11, §3): prepara a amostra, roda o juiz e coleta rótulos humanos.

Uso:
    python scripts/aula11_rotular.py --preparar               # amostra 32 execuções da suíte e roda o juiz
    python scripts/aula11_rotular.py --rotular --rotulador Ana  # rotulagem interativa (humano)

A rotulagem esconde o veredito do juiz de quem rotula — ver o veredito antes ancora o rótulo, e
a validação passaria a medir a concordância do humano com o juiz, não o contrário.

Parâmetros:
- `TAMANHO_AMOSTRA = 32`: o mínimo é 30; 32 deixa margem para descartar duas amostras ilegíveis.
- Amostra estratificada por classe e versão, com semente fixa: todo o grupo rotula as MESMAS
  amostras, e uma segunda rodada de rotulagem é comparável à primeira.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv

load_dotenv()

from src.core.llm_client import cliente_ativo_ou_none  # noqa: E402
from src.evals.juiz import CAMINHO_ROTULOS, COLUNAS_ROTULOS, JuizFundamentacao, ler_rotulos, resultados_para_juiz  # noqa: E402
from src.evals.suite import PASTA_EXECUCOES  # noqa: E402

TAMANHO_AMOSTRA = 32
SEMENTE = 20261009


def preparar() -> None:
    cliente, modelo = cliente_ativo_ou_none()
    if cliente is None:
        raise SystemExit(f"Precisa do LLM para rodar o juiz: {modelo}")
    execucoes = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(PASTA_EXECUCOES.rglob("G*.json"))]
    if len(execucoes) < TAMANHO_AMOSTRA:
        raise SystemExit(f"Só {len(execucoes)} execuções gravadas; rode antes scripts/aula11_suite.py.")

    rnd = random.Random(SEMENTE)
    por_estrato: dict[tuple, list[dict]] = {}
    for e in execucoes:
        por_estrato.setdefault((e["classe"], e["versao"]), []).append(e)
    amostra: list[dict] = []
    estratos = sorted(por_estrato)
    while len(amostra) < TAMANHO_AMOSTRA:
        for chave in estratos:
            if por_estrato[chave] and len(amostra) < TAMANHO_AMOSTRA:
                amostra.append(por_estrato[chave].pop(rnd.randrange(len(por_estrato[chave]))))

    juiz = JuizFundamentacao(cliente, modelo)
    existentes = {l["amostra_id"]: l for l in ler_rotulos()}
    linhas = []
    for i, e in enumerate(amostra, start=1):
        amostra_id = f"{e['versao']}-rep{e['repeticao']}-{e['caso_id']}"
        if amostra_id in existentes:
            linhas.append(existentes[amostra_id])
            continue
        resultados = resultados_para_juiz(e["trajetoria"])
        v = juiz.julgar(e["entrada"], resultados, e["resposta"])
        print(f"  [{i}/{TAMANHO_AMOSTRA}] {amostra_id}: juiz={v.fundamentada}")
        linhas.append({
            "amostra_id": amostra_id, "caso_id": e["caso_id"], "versao": e["versao"], "repeticao": e["repeticao"],
            "pergunta": e["entrada"], "resultados_ferramentas": resultados, "resposta": e["resposta"],
            "rotulo_humano": "", "nota_humana": "", "rotulador": "",
            "veredito_juiz": "" if v.fundamentada is None else ("sim" if v.fundamentada else "nao"),
            "justificativa_juiz": v.justificativa or v.erro or "", "classificacao_desacordo": "",
        })
    salvar(linhas)
    print(f"Amostra com {len(linhas)} execuções em {CAMINHO_ROTULOS} (juiz: {juiz.modelo}).")


def salvar(linhas: list[dict]) -> None:
    CAMINHO_ROTULOS.parent.mkdir(parents=True, exist_ok=True)
    with CAMINHO_ROTULOS.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUNAS_ROTULOS)
        w.writeheader()
        w.writerows(linhas)


def rotular(rotulador: str) -> None:
    linhas = ler_rotulos()
    if not linhas:
        raise SystemExit("Sem amostra: rode antes com --preparar.")
    pendentes = [l for l in linhas if not l["rotulo_humano"].strip()]
    print(f"{len(pendentes)} amostras sem rótulo. Critério: TODA afirmação factual da resposta está nos resultados "
          "das ferramentas (ou é conta simples sobre eles, ou regra geral do prompt)? Uma afirmação sem base = não.\n")
    for l in pendentes:
        print("=" * 100)
        print(f"{l['amostra_id']}\nPERGUNTA: {l['pergunta']}\n\nRESULTADOS DAS FERRAMENTAS:\n{l['resultados_ferramentas']}\n")
        print(f"RESPOSTA:\n{l['resposta']}\n")
        while (r := input("Fundamentada? [s/n, q para sair] ").strip().lower()) not in ("s", "n", "q"):
            pass
        if r == "q":
            break
        l["rotulo_humano"] = "sim" if r == "s" else "nao"
        l["nota_humana"] = input("Nota (por que; obrigatória): ").strip() or "(sem nota)"
        l["rotulador"] = rotulador
        salvar(linhas)
    print("\nRótulos salvos. Para os desacordos, preencha 'classificacao_desacordo' com juiz | rubrica | rotulo.")


def main() -> None:
    parser = argparse.ArgumentParser()
    grupo = parser.add_mutually_exclusive_group(required=True)
    grupo.add_argument("--preparar", action="store_true")
    grupo.add_argument("--rotular", action="store_true")
    parser.add_argument("--rotulador", default="")
    args = parser.parse_args()
    if args.preparar:
        preparar()
    else:
        if not args.rotulador:
            raise SystemExit("--rotulador NOME é obrigatório: o rótulo sem autor não vale como validação.")
        rotular(args.rotulador)


if __name__ == "__main__":
    main()
