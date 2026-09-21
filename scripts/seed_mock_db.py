"""Cria dados/precos_mock.db — espelho local do banco de preços real do fractal-precos.

Lê dados/seed_precos.csv (scripts/gerar_dados_sinteticos.py) e monta o MESMO schema
normalizado e as mesmas views (vw_PrecoAtual, vw_Ruptura) descritas em
fractal-precos/docs/schema-sql-server.md, em dialeto SQLite.

src/projects/farmacia_precos/db.py consulta esse espelho com o mesmo SQL que usaria
contra o SQL Server real — só a conexão muda, via FRACTALPRECOS_CONNECTION_STRING no
.env. Rode de novo sempre que mudar dados/seed_precos.csv: o banco é recriado do zero.
"""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

CAMINHO_CSV = Path(__file__).resolve().parents[1] / "dados" / "seed_precos.csv"
CAMINHO_DB = Path(__file__).resolve().parents[1] / "dados" / "precos_mock.db"

DDL_TABELAS = """
CREATE TABLE Fabricante (
    Id INTEGER PRIMARY KEY,
    Nome TEXT UNIQUE NOT NULL
);
CREATE TABLE Marca (
    Id INTEGER PRIMARY KEY,
    Nome TEXT UNIQUE NOT NULL,
    FabricanteId INTEGER REFERENCES Fabricante(Id)
);
CREATE TABLE Produto (
    Id INTEGER PRIMARY KEY,
    Nome TEXT NOT NULL,
    PrincipioAtivo TEXT,
    MarcaId INTEGER NOT NULL REFERENCES Marca(Id),
    EhReferencia INTEGER NOT NULL DEFAULT 0,
    ProdutoReferenciaId INTEGER REFERENCES Produto(Id)
);
CREATE TABLE Farmacia (
    Id INTEGER PRIMARY KEY,
    Nome TEXT UNIQUE NOT NULL
);
CREATE TABLE ProdutoFarmacia (
    Id INTEGER PRIMARY KEY,
    ProdutoId INTEGER NOT NULL REFERENCES Produto(Id),
    FarmaciaId INTEGER NOT NULL REFERENCES Farmacia(Id),
    SkuFarmacia TEXT NOT NULL,
    EanObservado TEXT,
    UNIQUE (FarmaciaId, SkuFarmacia)
);
CREATE TABLE ProgramaPBM (
    Id INTEGER PRIMARY KEY,
    Nome TEXT UNIQUE NOT NULL,
    FabricanteId INTEGER REFERENCES Fabricante(Id)
);
CREATE TABLE PrecoColetado (
    Id INTEGER PRIMARY KEY,
    ProdutoFarmaciaId INTEGER NOT NULL REFERENCES ProdutoFarmacia(Id),
    DataHoraColeta TEXT NOT NULL,
    PrecoTabela REAL NOT NULL,
    PrecoFarmacia REAL NOT NULL,
    PrecoPbm REAL,
    ProgramaPbmId INTEGER REFERENCES ProgramaPBM(Id),
    Disponivel INTEGER NOT NULL DEFAULT 1
);
"""

# Mesma lógica de fractal-precos/docs/schema-sql-server.md §3, em dialeto SQLite
# (ROWS BETWEEN ... explícito, DATEDIFF -> julianday — SQLite não aceita a forma curta
# nem a função proprietária do SQL Server).
DDL_VIEWS = """
CREATE VIEW vw_PrecoAtual AS
WITH Ultimo AS (
    SELECT pc.*,
           ROW_NUMBER() OVER (PARTITION BY pc.ProdutoFarmaciaId ORDER BY pc.DataHoraColeta DESC) AS rn
    FROM PrecoColetado pc
)
SELECT
    u.ProdutoFarmaciaId,
    u.DataHoraColeta AS DataUltimaColeta,
    f.Nome AS Farmacia,
    p.Nome AS Produto,
    p.PrincipioAtivo,
    m.Nome AS Marca,
    fab.Nome AS Fabricante,
    pf.EanObservado,
    u.PrecoTabela,
    u.PrecoFarmacia,
    u.PrecoPbm,
    pb.Nome AS ProgramaPbmNome,
    u.Disponivel
FROM Ultimo u
JOIN ProdutoFarmacia pf ON pf.Id = u.ProdutoFarmaciaId
JOIN Farmacia f ON f.Id = pf.FarmaciaId
JOIN Produto p ON p.Id = pf.ProdutoId
JOIN Marca m ON m.Id = p.MarcaId
LEFT JOIN Fabricante fab ON fab.Id = m.FabricanteId
LEFT JOIN ProgramaPBM pb ON pb.Id = u.ProgramaPbmId
WHERE u.rn = 1;

CREATE VIEW vw_Ruptura AS
WITH Ordenado AS (
    SELECT
        pc.ProdutoFarmaciaId,
        pc.DataHoraColeta,
        pc.Disponivel,
        LAG(pc.Disponivel) OVER (PARTITION BY pc.ProdutoFarmaciaId ORDER BY pc.DataHoraColeta) AS DisponivelAnterior
    FROM PrecoColetado pc
),
Transicoes AS (
    SELECT *,
        CASE WHEN DisponivelAnterior IS NULL OR DisponivelAnterior <> Disponivel THEN 1 ELSE 0 END AS MudouEstado
    FROM Ordenado
),
Grupos AS (
    SELECT *,
        SUM(MudouEstado) OVER (
            PARTITION BY ProdutoFarmaciaId ORDER BY DataHoraColeta
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS GrupoEstado
    FROM Transicoes
),
UltimoGrupo AS (
    SELECT
        ProdutoFarmaciaId,
        Disponivel,
        MIN(DataHoraColeta) AS DesdeQuando,
        MAX(DataHoraColeta) AS UltimaColeta,
        COUNT(*) AS QtdColetasNesseEstado,
        ROW_NUMBER() OVER (PARTITION BY ProdutoFarmaciaId ORDER BY MAX(DataHoraColeta) DESC) AS rn
    FROM Grupos
    GROUP BY ProdutoFarmaciaId, Disponivel, GrupoEstado
)
SELECT
    ug.ProdutoFarmaciaId,
    f.Nome AS Farmacia,
    p.Nome AS Produto,
    ug.Disponivel,
    ug.DesdeQuando,
    ug.UltimaColeta,
    CAST(julianday(ug.UltimaColeta) - julianday(ug.DesdeQuando) AS INTEGER) AS DiasNoEstadoAtual,
    ug.QtdColetasNesseEstado
FROM UltimoGrupo ug
JOIN ProdutoFarmacia pf ON pf.Id = ug.ProdutoFarmaciaId
JOIN Farmacia f ON f.Id = pf.FarmaciaId
JOIN Produto p ON p.Id = pf.ProdutoId
WHERE ug.rn = 1;
"""


def _get_or_create(cursor: sqlite3.Cursor, tabela: str, nome: str, extra_cols: dict | None = None) -> int:
    extra_cols = extra_cols or {}
    cursor.execute(f"SELECT Id FROM {tabela} WHERE Nome = ?", (nome,))
    linha = cursor.fetchone()
    if linha:
        return linha[0]
    colunas = ["Nome", *extra_cols.keys()]
    valores = [nome, *extra_cols.values()]
    marcadores = ", ".join("?" for _ in colunas)
    cursor.execute(f"INSERT INTO {tabela} ({', '.join(colunas)}) VALUES ({marcadores})", valores)
    return cursor.lastrowid


def main() -> None:
    if not CAMINHO_CSV.exists():
        raise SystemExit(f"{CAMINHO_CSV} não existe — rode antes: python scripts/gerar_dados_sinteticos.py")

    CAMINHO_DB.unlink(missing_ok=True)
    conn = sqlite3.connect(CAMINHO_DB)
    cursor = conn.cursor()
    cursor.executescript(DDL_TABELAS)

    produto_id_por_nome: dict[str, int] = {}
    pendentes_referencia: list[tuple[int, str]] = []

    with CAMINHO_CSV.open(encoding="utf-8") as f:
        linhas = list(csv.DictReader(f))

    for linha in linhas:
        fabricante_id = _get_or_create(cursor, "Fabricante", linha["fabricante"])
        marca_id = _get_or_create(cursor, "Marca", linha["marca"], {"FabricanteId": fabricante_id})
        farmacia_id = _get_or_create(cursor, "Farmacia", linha["farmacia"])

        if linha["produto"] not in produto_id_por_nome:
            cursor.execute(
                "INSERT INTO Produto (Nome, PrincipioAtivo, MarcaId, EhReferencia) VALUES (?, ?, ?, ?)",
                (linha["produto"], linha["principio_ativo"], marca_id, int(linha["eh_referencia"])),
            )
            produto_id_por_nome[linha["produto"]] = cursor.lastrowid
            if linha["produto_referencia"]:
                pendentes_referencia.append((cursor.lastrowid, linha["produto_referencia"]))
        produto_id = produto_id_por_nome[linha["produto"]]

        cursor.execute(
            "SELECT Id FROM ProdutoFarmacia WHERE ProdutoId = ? AND FarmaciaId = ?",
            (produto_id, farmacia_id),
        )
        pf = cursor.fetchone()
        if pf:
            produto_farmacia_id = pf[0]
        else:
            cursor.execute(
                "INSERT INTO ProdutoFarmacia (ProdutoId, FarmaciaId, SkuFarmacia) VALUES (?, ?, ?)",
                (produto_id, farmacia_id, linha["sku_farmacia"]),
            )
            produto_farmacia_id = cursor.lastrowid

        programa_pbm_id = None
        if linha["programa_pbm"]:
            programa_pbm_id = _get_or_create(
                cursor, "ProgramaPBM", linha["programa_pbm"], {"FabricanteId": fabricante_id}
            )

        cursor.execute(
            """INSERT INTO PrecoColetado
               (ProdutoFarmaciaId, DataHoraColeta, PrecoTabela, PrecoFarmacia, PrecoPbm, ProgramaPbmId, Disponivel)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                produto_farmacia_id,
                linha["data_hora_coleta"],
                float(linha["preco_tabela"]),
                float(linha["preco_farmacia"]),
                float(linha["preco_pbm"]) if linha["preco_pbm"] else None,
                programa_pbm_id,
                int(linha["disponivel"]),
            ),
        )

    for produto_id, nome_referencia in pendentes_referencia:
        referencia_id = produto_id_por_nome.get(nome_referencia)
        if referencia_id:
            cursor.execute("UPDATE Produto SET ProdutoReferenciaId = ? WHERE Id = ?", (referencia_id, produto_id))

    cursor.executescript(DDL_VIEWS)
    conn.commit()

    (n_produtos,) = cursor.execute("SELECT COUNT(*) FROM Produto").fetchone()
    (n_farmacias,) = cursor.execute("SELECT COUNT(*) FROM Farmacia").fetchone()
    (n_precos,) = cursor.execute("SELECT COUNT(*) FROM PrecoColetado").fetchone()
    conn.close()

    print(f"Espelho criado em {CAMINHO_DB}")
    print(f"  {n_produtos} produtos, {n_farmacias} farmácias, {n_precos} preços coletados.")


if __name__ == "__main__":
    main()
