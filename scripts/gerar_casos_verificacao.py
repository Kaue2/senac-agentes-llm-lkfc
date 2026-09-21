"""Gera dados/casos_verificacao.csv — o conjunto rotulado do verificador (docs/case.md §6).

Cada valor_esperado é calculado direto do espelho (mesma view que a ferramenta do agente
usa), não digitado à mão — para não introduzir um segundo lugar onde o número pudesse
divergir do dado real. As perguntas de categoria "inexistente" são a exceção: o valor
esperado é sempre "nao_encontrado", por construção (ver scripts/gerar_dados_sinteticos.py
sobre por que Ivermectina/Extrafarma não existem no cadastro sintético).
"""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

CAMINHO_DB = Path(__file__).resolve().parents[1] / "dados" / "precos_mock.db"
CAMINHO_SAIDA = Path(__file__).resolve().parents[1] / "dados" / "casos_verificacao.csv"


def buscar_um(cur, sql, params):
    cur.execute(sql, params)
    linha = cur.fetchone()
    if linha is None:
        raise SystemExit(f"Consulta não retornou linha (dado sintético mudou?): {sql} {params}")
    return linha[0]


def main() -> None:
    conn = sqlite3.connect(CAMINHO_DB)
    cur = conn.cursor()
    casos: list[dict] = []

    def add(pergunta, farmacia, produto, campo, categoria, sql, params):
        valor = buscar_um(cur, sql, params)
        casos.append(
            {
                "pergunta": pergunta,
                "farmacia": farmacia,
                "produto": produto,
                "campo_esperado": campo,
                "valor_esperado": "" if valor is None else valor,
                "categoria_do_caso": categoria,
            }
        )

    # --- simples ---
    add(
        "Qual o preço de tabela da Trayenta 5mg na Araujo?", "Araujo", "Trayenta 5mg", "PrecoTabela", "simples",
        "SELECT PrecoTabela FROM vw_PrecoAtual WHERE Produto LIKE '%Trayenta%' AND Farmacia = ?", ("Araujo",),
    )
    add(
        "Qual o preço de farmácia da Novalgina 500mg na Raia?", "Raia", "Novalgina 500mg", "PrecoFarmacia", "simples",
        "SELECT PrecoFarmacia FROM vw_PrecoAtual WHERE Produto LIKE '%Novalgina%' AND Farmacia = ?", ("Raia",),
    )
    add(
        "Qual o preço com desconto de PBM da Trayenta 5mg na Pacheco?", "Pacheco", "Trayenta 5mg", "PrecoPbm", "simples",
        "SELECT PrecoPbm FROM vw_PrecoAtual WHERE Produto LIKE '%Trayenta%' AND Farmacia = ?", ("Pacheco",),
    )

    # --- divergência (o valor esperado é sempre o real da farmácia, não o que o usuário afirma) ---
    for farmacia in ["Drogasil", "Araujo", "Venancio"]:
        add(
            f"O usuário afirma um valor diferente para a Trayenta 5mg na {farmacia} — qual é o preço de farmácia real?",
            farmacia, "Trayenta 5mg", "PrecoFarmacia", "divergencia",
            "SELECT PrecoFarmacia FROM vw_PrecoAtual WHERE Produto LIKE '%Trayenta%' AND Farmacia = ?", (farmacia,),
        )

    # --- sem_pbm (produto que nunca tem PrecoPbm) ---
    add(
        "A Linagliptina 5mg genérica tem desconto de PBM na Araujo?", "Araujo", "Linagliptina 5mg (genérico)",
        "PrecoPbm", "sem_pbm",
        "SELECT PrecoPbm FROM vw_PrecoAtual WHERE Produto LIKE '%gen%rico%' AND Farmacia = ?", ("Araujo",),
    )
    add(
        "A Linagliptina 5mg genérica tem desconto de PBM na Drogasil?", "Drogasil", "Linagliptina 5mg (genérico)",
        "PrecoPbm", "sem_pbm",
        "SELECT PrecoPbm FROM vw_PrecoAtual WHERE Produto LIKE '%gen%rico%' AND Farmacia = ?", ("Drogasil",),
    )
    add(
        "A Novalgina 500mg tem desconto de PBM na Araujo?", "Araujo", "Novalgina 500mg", "PrecoPbm", "sem_pbm",
        "SELECT PrecoPbm FROM vw_PrecoAtual WHERE Produto LIKE '%Novalgina%' AND Farmacia = ?", ("Araujo",),
    )

    # --- ruptura ---
    add(
        "O Ozempic 1mg está disponível na Drogasil?", "Drogasil", "Ozempic 1mg", "Disponivel", "ruptura",
        "SELECT Disponivel FROM vw_Ruptura WHERE Produto LIKE '%Ozempic%' AND Farmacia = ?", ("Drogasil",),
    )
    add(
        "Desde quando o Ozempic 1mg está no estado atual (disponível/indisponível) na Drogasil?",
        "Drogasil", "Ozempic 1mg", "DesdeQuando", "ruptura",
        "SELECT DesdeQuando FROM vw_Ruptura WHERE Produto LIKE '%Ozempic%' AND Farmacia = ?", ("Drogasil",),
    )
    add(
        "Há quantos dias o Ozempic 1mg está nesse estado na Drogasil?", "Drogasil", "Ozempic 1mg",
        "DiasNoEstadoAtual", "ruptura",
        "SELECT DiasNoEstadoAtual FROM vw_Ruptura WHERE Produto LIKE '%Ozempic%' AND Farmacia = ?", ("Drogasil",),
    )

    # --- inexistente (por construção: não existem no cadastro sintético) ---
    for pergunta, farmacia, produto in [
        ("Qual o preço da Ivermectina 6mg na farmácia Extrafarma?", "Extrafarma", "Ivermectina 6mg"),
        ("Qual o preço da Ivermectina 6mg na Araujo?", "Araujo", "Ivermectina 6mg"),
        ("Qual o preço da Trayenta 5mg na farmácia Extrafarma?", "Extrafarma", "Trayenta 5mg"),
    ]:
        casos.append(
            {
                "pergunta": pergunta,
                "farmacia": farmacia,
                "produto": produto,
                "campo_esperado": "encontrado",
                "valor_esperado": "nao_encontrado",
                "categoria_do_caso": "inexistente",
            }
        )

    conn.close()

    with CAMINHO_SAIDA.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(casos[0].keys()))
        writer.writeheader()
        writer.writerows(casos)

    print(f"Gerado {CAMINHO_SAIDA} com {len(casos)} casos.")


if __name__ == "__main__":
    main()
