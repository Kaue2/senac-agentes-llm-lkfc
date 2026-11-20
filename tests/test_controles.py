"""Os controles de segurança da Parte 3 (docs/seguranca.md §2). Cada teste TENTA a ação indevida e
confere que ela foi bloqueada — fora do prompt, em código."""

from __future__ import annotations

import sqlite3

import pytest

from src.projects.farmacia_precos import db
from src.projects.farmacia_precos.db import exigir_somente_leitura


# ---------------------------------------------------------------- C1 — somente leitura no banco
@pytest.mark.parametrize("sql", [
    "UPDATE PrecoColetado SET PrecoFarmacia = 1",
    "DELETE FROM Produto",
    "SELECT * FROM Produto; DROP TABLE Produto",
    "/* comentário */ INSERT INTO Farmacia (Nome) VALUES ('x')",
    "  drop table Farmacia",
])
def test_c1_portao_bloqueia_escrita(sql):
    with pytest.raises(PermissionError):
        exigir_somente_leitura(sql)


def test_c1_portao_deixa_passar_as_consultas_do_sistema():
    for sql in ("SELECT * FROM vw_PrecoAtual WHERE Produto LIKE ?", "-- comentário\nSELECT 1", "WITH x AS (SELECT 1) SELECT * FROM x"):
        exigir_somente_leitura(sql)


def test_c1_espelho_aberto_somente_leitura(tmp_path, monkeypatch):
    caminho = tmp_path / "espelho.db"
    with sqlite3.connect(caminho) as c:
        c.execute("CREATE TABLE Produto (Nome TEXT)")
    monkeypatch.setattr(db, "CAMINHO_ESPELHO_SQLITE", caminho)
    monkeypatch.setenv("FRACTALPRECOS_CONNECTION_STRING", "")
    banco = db.BancoPrecos()
    try:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            banco._conn.execute("INSERT INTO Produto VALUES ('x')")  # mesmo contornando o portão
        with pytest.raises(PermissionError):
            banco._query("DELETE FROM Produto", ())
    finally:
        banco.close()
