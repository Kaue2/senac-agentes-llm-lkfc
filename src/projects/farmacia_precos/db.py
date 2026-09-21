"""Acesso de LEITURA ao banco de preços real do fractal-precos.

Esta é a integração exigida pelo item 4.2 (uma ferramenta que conversa com software
tradicional, não com o modelo): tenta conectar no SQL Server real via
FRACTALPRECOS_CONNECTION_STRING — a mesma connection string do projeto .NET
fractal-precos (ver ../fractal-precos/docs/schema-sql-server.md). Se a variável estiver
vazia ou a conexão falhar (rede/VPN indisponível, driver ODBC ausente, etc.), cai
automaticamente para um espelho local em SQLite com o MESMO schema e as MESMAS views
(scripts/seed_mock_db.py) — nenhuma consulta abaixo muda entre as duas fontes.

Isso é deliberado: o item 4.1 pede "erro de ferramenta como dado, não exceção que
derruba" — aqui aplicamos o mesmo princípio um nível abaixo, na conexão: falha de rede
vira uma troca de fonte de dados, não uma exceção não tratada.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

PASTA_DADOS = Path(__file__).resolve().parents[3] / "dados"
CAMINHO_ESPELHO_SQLITE = PASTA_DADOS / "precos_mock.db"

# fractal-precos (projeto .NET) guarda a connection string no formato ADO.NET
# ("Data Source=...;Initial Catalog=...;User ID=...;Password=..."), que usa nomes de
# chave diferentes do que o driver ODBC espera ("Server", "Database", "UID", "PWD").
# Isso deixa colar a MESMA string do appsettings.Local.json de lá direto no .env daqui,
# sem o time precisar traduzir a mão.
_ALIAS_CHAVE_ADO_PARA_ODBC = {
    "data source": "Server",
    "server": "Server",
    "address": "Server",
    "addr": "Server",
    "network address": "Server",
    "initial catalog": "Database",
    "database": "Database",
    "user id": "UID",
    "uid": "UID",
    "user": "UID",
    "password": "PWD",
    "pwd": "PWD",
    "encrypt": "Encrypt",
    "trustservercertificate": "TrustServerCertificate",
}
# Chaves só fazem sentido no ADO.NET (pooling do lado do cliente .NET, timeout de
# comando) — o driver ODBC não entende, então descartamos ao traduzir.
_CHAVES_IGNORADAS_NA_TRADUCAO = {"persist security info", "pooling", "multipleactiveresultsets", "command timeout"}


def _normalizar_booleano_odbc(valor: str) -> str:
    return "yes" if valor.strip().lower() in {"true", "yes", "1"} else "no"


def _traduzir_connection_string_para_odbc(connection_string: str, driver: str = "ODBC Driver 17 for SQL Server") -> str:
    """Se a string já vier no formato ODBC (tem 'DRIVER='), usa como está. Senão,
    assume formato ADO.NET/.NET (o do fractal-precos) e traduz."""
    if "driver=" in connection_string.lower():
        return connection_string

    partes_odbc = {"Driver": f"{{{driver}}}"}
    for trecho in connection_string.split(";"):
        if "=" not in trecho:
            continue
        chave, valor = trecho.split("=", 1)
        chave_normalizada = chave.strip().lower()
        valor = valor.strip()
        if chave_normalizada in _CHAVES_IGNORADAS_NA_TRADUCAO or not valor:
            continue
        chave_odbc = _ALIAS_CHAVE_ADO_PARA_ODBC.get(chave_normalizada)
        if chave_odbc is None:
            continue
        if chave_odbc in ("Encrypt", "TrustServerCertificate"):
            valor = _normalizar_booleano_odbc(valor)
        partes_odbc[chave_odbc] = valor

    return ";".join(f"{chave}={valor}" for chave, valor in partes_odbc.items())


class BancoPrecos:
    def __init__(self) -> None:
        self._conn: Any = None
        self.fonte: str
        self.motivo_fallback: str | None = None

        connection_string = os.environ.get("FRACTALPRECOS_CONNECTION_STRING", "").strip()
        if connection_string:
            try:
                import pyodbc

                connection_string_odbc = _traduzir_connection_string_para_odbc(connection_string)
                self._conn = pyodbc.connect(connection_string_odbc, timeout=5)
                self.fonte = "sql_server_real"
            except Exception as exc:
                self.motivo_fallback = str(exc)

        if self._conn is None:
            if not CAMINHO_ESPELHO_SQLITE.exists():
                raise RuntimeError(
                    "Espelho local não encontrado. Rode: "
                    "python scripts/gerar_dados_sinteticos.py && python scripts/seed_mock_db.py"
                )
            self._conn = sqlite3.connect(CAMINHO_ESPELHO_SQLITE)
            self.fonte = "espelho_sqlite"

    def close(self) -> None:
        self._conn.close()

    def _query(self, sql: str, params: tuple) -> list[dict]:
        cursor = self._conn.cursor()
        cursor.execute(sql, params)
        colunas = [c[0] for c in cursor.description]
        linhas = [dict(zip(colunas, linha)) for linha in cursor.fetchall()]
        cursor.close()
        return linhas

    def preco_atual(self, produto: str, farmacia: str | None = None) -> list[dict]:
        """Preço mais recente por produto/farmácia — sempre via vw_PrecoAtual, nunca
        lendo PrecoColetado bruto (mesma regra do fractal-precos, ver schema-sql-server.md §4.1)."""
        sql = "SELECT * FROM vw_PrecoAtual WHERE Produto LIKE ?"
        params: list[Any] = [f"%{produto}%"]
        if farmacia:
            sql += " AND Farmacia LIKE ?"
            params.append(f"%{farmacia}%")
        return self._query(sql, tuple(params))

    def historico_precos(self, produto: str, farmacia: str | None = None, dias: int = 30) -> list[dict]:
        cutoff = (datetime.utcnow() - timedelta(days=dias)).strftime("%Y-%m-%d %H:%M:%S")
        sql = (
            "SELECT f.Nome AS Farmacia, p.Nome AS Produto, pc.DataHoraColeta, "
            "pc.PrecoTabela, pc.PrecoFarmacia, pc.PrecoPbm, pc.Disponivel "
            "FROM PrecoColetado pc "
            "JOIN ProdutoFarmacia pf ON pf.Id = pc.ProdutoFarmaciaId "
            "JOIN Farmacia f ON f.Id = pf.FarmaciaId "
            "JOIN Produto p ON p.Id = pf.ProdutoId "
            "WHERE p.Nome LIKE ? AND pc.DataHoraColeta >= ?"
        )
        params: list[Any] = [f"%{produto}%", cutoff]
        if farmacia:
            sql += " AND f.Nome LIKE ?"
            params.append(f"%{farmacia}%")
        sql += " ORDER BY pc.DataHoraColeta DESC"
        return self._query(sql, tuple(params))

    def status_ruptura(self, produto: str, farmacia: str | None = None) -> list[dict]:
        """Situação de disponibilidade — via vw_Ruptura, nunca calculado ad-hoc (mesma
        regra do fractal-precos: LAG()/agrupamento por transição, não flag isolado por dia)."""
        sql = "SELECT * FROM vw_Ruptura WHERE Produto LIKE ?"
        params: list[Any] = [f"%{produto}%"]
        if farmacia:
            sql += " AND Farmacia LIKE ?"
            params.append(f"%{farmacia}%")
        return self._query(sql, tuple(params))
