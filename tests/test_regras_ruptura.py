"""A correção da Parte 2: as regras de ruptura do corpus aplicadas em código, na ferramenta."""

from __future__ import annotations

from datetime import date

from src.projects.farmacia_precos.tools_farmacia import data_referencia, situacao_da_linha


def test_coleta_antiga_vira_sem_coleta_recente_mesmo_indisponivel():
    linha = {"UltimaColeta": "2026-09-19 00:00:00", "Disponivel": 0, "QtdColetasNesseEstado": 4}
    s = situacao_da_linha(linha, "ruptura", date(2026, 11, 20))
    assert s["situacao_coleta"] == "sem_coleta_recente" and "situacao_ruptura" not in s
    assert s["dias_desde_ultima_coleta"] == 62


def test_ruptura_confirmada_e_a_confirmar():
    hoje = date(2026, 9, 20)
    assert situacao_da_linha({"UltimaColeta": "2026-09-19", "Disponivel": 0, "QtdColetasNesseEstado": 2}, "ruptura", hoje)["situacao_ruptura"] == "ruptura_confirmada"
    assert situacao_da_linha({"UltimaColeta": "2026-09-19", "Disponivel": 0, "QtdColetasNesseEstado": 1}, "ruptura", hoje)["situacao_ruptura"] == "ruptura_a_confirmar"
    assert situacao_da_linha({"UltimaColeta": "2026-09-19", "Disponivel": 1, "QtdColetasNesseEstado": 9}, "ruptura", hoje)["situacao_ruptura"] == "disponivel"


def test_limite_de_tres_dias_e_inclusivo():
    assert situacao_da_linha({"DataUltimaColeta": "2026-09-17 00:00:00"}, "atual", date(2026, 9, 20))["situacao_coleta"] == "recente"
    assert situacao_da_linha({"DataUltimaColeta": "2026-09-16 00:00:00"}, "atual", date(2026, 9, 20))["situacao_coleta"] == "sem_coleta_recente"


def test_data_de_referencia_fixada_pelo_ambiente(monkeypatch):
    monkeypatch.setenv("AGENT_DATA_REFERENCIA", "2026-09-20")
    assert data_referencia() == date(2026, 9, 20)
    monkeypatch.delenv("AGENT_DATA_REFERENCIA")
    assert data_referencia() == date.today()
