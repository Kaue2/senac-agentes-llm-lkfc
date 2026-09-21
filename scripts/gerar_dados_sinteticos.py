"""Gera dados/seed_precos.csv — dados sintéticos do pilar "preço" do case de farmácia.

Os valores são ilustrativos (ver docs/case.md), mas a ordem de grandeza e as regras
seguem o levantamento real documentado em fractal-precos/docs/modelo-dados-preco.md
(PMC ~R$300-350 para a Trayenta 5mg, desconto de PBM ~35% quando existe programa).

Casos difíceis nomeados aqui (docs/case.md §2.8, usados nas 4 demonstrações do item 4.5
e no conjunto rotulado do verificador, item 2.6):

- **caso_divergencia**: Trayenta 5mg na Drogasil. Um gestor pode se lembrar de um preço
  de memória (ex.: "R$150") que não bate com o preço de farmácia coletado (sem PBM) —
  o agente precisa confiar na fonte de dados e explicar a diferença, não concordar
  com o usuário nem inventar um valor de meio-termo.
- **caso_ruptura**: Ozempic 1mg só existe cadastrado na Drogasil, e fica indisponível
  (Disponivel=0) nos últimos dias da série — testa `vw_Ruptura`.
- **caso_generico_sem_pbm**: Linagliptina 5mg (genérico) nunca tem PrecoPbm, ao
  contrário da Trayenta (produto de referência) — testa se o agente confunde os dois.
- **registro inexistente**: propositalmente NÃO geramos aqui nenhum produto chamado
  "Ivermectina" nem uma farmácia "Extrafarma" — são usados nas demonstrações exatamente
  por não existirem no cadastro, para checar o comportamento de erro de ferramenta.
"""

from __future__ import annotations

import csv
import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

ARQUIVO_SAIDA = Path(__file__).resolve().parents[1] / "dados" / "seed_precos.csv"
DATA_FINAL = datetime(2026, 9, 19)
DIAS_DE_HISTORICO = 10
random.seed(42)


@dataclass
class Produto:
    nome: str
    fabricante: str
    marca: str
    principio_ativo: str
    eh_referencia: bool
    produto_referencia: str | None
    preco_tabela_base: float
    desconto_farmacia_pct: float
    programa_pbm: str | None
    desconto_pbm_pct: float | None


PRODUTOS = [
    Produto(
        nome="Trayenta 5mg",
        fabricante="Boehringer Ingelheim",
        marca="Trayenta",
        principio_ativo="Linagliptina",
        eh_referencia=True,
        produto_referencia=None,
        preco_tabela_base=335.42,
        desconto_farmacia_pct=0.03,
        programa_pbm="Abraçar a Vida - Boehringer",
        desconto_pbm_pct=0.35,
    ),
    Produto(
        nome="Linagliptina 5mg (genérico)",
        fabricante="EMS",
        marca="EMS Genéricos",
        principio_ativo="Linagliptina",
        eh_referencia=False,
        produto_referencia="Trayenta 5mg",
        preco_tabela_base=198.90,
        desconto_farmacia_pct=0.10,
        programa_pbm=None,
        desconto_pbm_pct=None,
    ),
    Produto(
        nome="Novalgina 500mg",
        fabricante="Sanofi",
        marca="Novalgina",
        principio_ativo="Dipirona Monoidratada",
        eh_referencia=True,
        produto_referencia=None,
        preco_tabela_base=14.90,
        desconto_farmacia_pct=0.08,
        programa_pbm=None,
        desconto_pbm_pct=None,
    ),
    Produto(
        nome="Ozempic 1mg",
        fabricante="Novo Nordisk",
        marca="Ozempic",
        principio_ativo="Semaglutida",
        eh_referencia=True,
        produto_referencia=None,
        preco_tabela_base=1029.90,
        desconto_farmacia_pct=0.02,
        programa_pbm=None,
        desconto_pbm_pct=None,
    ),
]

# Nem todo produto está em toda farmácia — realista, e é o que sustenta o caso_ruptura
# (Ozempic só existe na Drogasil neste espelho).
DISPONIBILIDADE_POR_FARMACIA = {
    "Trayenta 5mg": ["Araujo", "Drogasil", "Raia", "Pacheco", "Venancio"],
    "Linagliptina 5mg (genérico)": ["Araujo", "Drogasil"],
    "Novalgina 500mg": ["Araujo", "Drogasil", "Raia", "Pacheco", "Venancio"],
    "Ozempic 1mg": ["Drogasil"],
}


def gerar_linhas() -> list[dict]:
    linhas = []
    contador_sku = 0
    for produto in PRODUTOS:
        for nome_farmacia in DISPONIBILIDADE_POR_FARMACIA[produto.nome]:
            contador_sku += 1
            sku = f"{nome_farmacia[:3].upper()}-{contador_sku:04d}"
            for dia in range(DIAS_DE_HISTORICO):
                data = DATA_FINAL - timedelta(days=DIAS_DE_HISTORICO - 1 - dia)
                jitter = random.uniform(-0.01, 0.01)
                preco_tabela = round(produto.preco_tabela_base * (1 + jitter), 2)
                preco_farmacia = round(preco_tabela * (1 - produto.desconto_farmacia_pct), 2)
                preco_pbm = (
                    round(preco_tabela * (1 - produto.desconto_pbm_pct), 2)
                    if produto.desconto_pbm_pct
                    else ""
                )

                disponivel = 1
                if produto.nome == "Ozempic 1mg" and nome_farmacia == "Drogasil" and dia >= DIAS_DE_HISTORICO - 4:
                    disponivel = 0  # caso_ruptura: indisponível nos últimos 4 dias da série

                linhas.append(
                    {
                        "fabricante": produto.fabricante,
                        "marca": produto.marca,
                        "produto": produto.nome,
                        "principio_ativo": produto.principio_ativo,
                        "eh_referencia": int(produto.eh_referencia),
                        "produto_referencia": produto.produto_referencia or "",
                        "farmacia": nome_farmacia,
                        "sku_farmacia": sku,
                        "data_hora_coleta": data.strftime("%Y-%m-%d %H:%M:%S"),
                        "preco_tabela": preco_tabela,
                        "preco_farmacia": preco_farmacia,
                        "preco_pbm": preco_pbm,
                        "programa_pbm": produto.programa_pbm or "",
                        "disponivel": disponivel,
                    }
                )
    return linhas


def main() -> None:
    linhas = gerar_linhas()
    ARQUIVO_SAIDA.parent.mkdir(parents=True, exist_ok=True)
    with ARQUIVO_SAIDA.open("w", newline="", encoding="utf-8") as f:
        campos = list(linhas[0].keys())
        writer = csv.DictWriter(f, fieldnames=campos)
        writer.writeheader()
        writer.writerows(linhas)
    print(f"Gerado {ARQUIVO_SAIDA} com {len(linhas)} linhas.")


if __name__ == "__main__":
    main()
