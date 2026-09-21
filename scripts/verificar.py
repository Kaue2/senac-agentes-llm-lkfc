"""O verificador (docs/case.md §6): roda o agente contra dados/casos_verificacao.csv e
mede o critério de sucesso do §7 — >=10/12 corretos nas categorias com valor numérico
(sem nunca confundir PrecoFarmacia com PrecoPbm), e 100% de "não encontrado" na
categoria inexistente.

Checagem por string matching simples — suficiente para o que a Parte 1 pede ("um teste
que passa ou falha"); não tenta parsear a resposta do modelo como uma estrutura.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # console Windows (cp1252) engasga em texto do modelo com acento
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()

from src.core.budget import Orcamento  # noqa: E402
from src.projects.farmacia_precos import config  # noqa: E402
from src.projects.farmacia_precos.fabrica import montar_agente  # noqa: E402

CAMINHO_CASOS = Path(__file__).resolve().parents[1] / "dados" / "casos_verificacao.csv"

TERMOS_NAO_ENCONTRADO = [
    "não encontr",
    "não há",
    "não tenho esse dado",
    "não existe",
    "sem esse dado",
    "não localizei",
    "não tenho registro",
    "não consta",
]


def valor_aparece_na_resposta(valor_esperado: str, resposta: str) -> bool:
    if not valor_esperado:
        return True
    resposta_com_virgula = resposta.replace(".", ",")
    return valor_esperado in resposta or valor_esperado.replace(".", ",") in resposta_com_virgula


def main() -> None:
    if not CAMINHO_CASOS.exists():
        raise SystemExit(f"{CAMINHO_CASOS} não existe — rode: python scripts/gerar_casos_verificacao.py")

    with CAMINHO_CASOS.open(encoding="utf-8") as f:
        casos = list(csv.DictReader(f))

    agente, banco, config_modelo = montar_agente()
    resultados = []
    try:
        for caso in casos:
            orcamento = Orcamento(max_passos=config.max_passos(), max_tokens=config.max_tokens())
            resultado = agente.executar(caso["pergunta"], orcamento)
            resposta = resultado.resposta_final or ""

            if caso["categoria_do_caso"] == "inexistente":
                acertou = any(termo in resposta.lower() for termo in TERMOS_NAO_ENCONTRADO)
            else:
                acertou = valor_aparece_na_resposta(str(caso["valor_esperado"]), resposta)

            resultados.append({**caso, "resposta_agente": resposta, "acertou": acertou})
            print(f"[{'OK' if acertou else 'FALHOU'}] ({caso['categoria_do_caso']}) {caso['pergunta']}")
    finally:
        banco.close()

    por_categoria: dict[str, list[bool]] = {}
    for r in resultados:
        por_categoria.setdefault(r["categoria_do_caso"], []).append(r["acertou"])

    print("\n--- Resumo por categoria ---")
    for categoria, acertos in por_categoria.items():
        print(f"{categoria}: {sum(acertos)}/{len(acertos)}")

    total_numericos = [r["acertou"] for r in resultados if r["categoria_do_caso"] != "inexistente"]
    print(f"\nCritério de sucesso (docs/case.md §7): {sum(total_numericos)}/{len(total_numericos)} (meta: >=10/12)")

    caminho_saida = config.PASTA_LOGS / "verificacao.csv"
    caminho_saida.parent.mkdir(parents=True, exist_ok=True)
    with caminho_saida.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(resultados[0].keys()))
        writer.writeheader()
        writer.writerows(resultados)
    print(f"\nResultado detalhado salvo em {caminho_saida}")


if __name__ == "__main__":
    main()
