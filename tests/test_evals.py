"""Testes dos avaliadores da suíte (Exercício 11): sem LLM.

Os testes mais importantes rodam os avaliadores sobre respostas REAIS da Parte 1
(logs/verificacao.csv) — os dois erros que o verificador da época cometeu viram regressão aqui.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.evals import avaliadores, regra
from src.evals.dataset import Caso, carregar_dataset, resumo, validar
from src.evals.juiz import concordancia
from src.evals.suite import executar_caso, pass_k, propriedade_pass_k, taxa, taxas_por_classe

RAIZ = Path(__file__).resolve().parents[1]


def _resposta_real_da_parte1(trecho_da_pergunta: str) -> str:
    with (RAIZ / "logs" / "verificacao.csv").open(encoding="utf-8") as f:
        return next(l["resposta_agente"] for l in csv.DictReader(f) if trecho_da_pergunta in l["pergunta"])


def _caso(cid: str) -> Caso:
    return next(c for c in carregar_dataset() if c.id == cid)


# ------------------------------------------------------------------ dataset
def test_dataset_cumpre_composicao():
    casos = carregar_dataset()
    r = resumo(casos)
    assert len(casos) >= 20
    assert len(r["por_classe"]) >= 3 and all(n >= 2 for n in r["por_classe"].values())
    assert r["por_classe"]["recusa"] >= 2 and r["por_classe"]["inexistente"] >= 2
    assert r["por_origem"]["desenvolvimento"] >= 1


def test_dataset_rejeita_origem_invalida():
    with pytest.raises(ValueError, match="origem"):
        validar([Caso("X", "?", "c", "inventada", "", "porque", {"valores": [["a"]]})])


# ------------------------------------- regressões do verificador da Parte 1
def test_falso_negativo_da_parte1_data_por_extenso_agora_passa():
    resposta = _resposta_real_da_parte1("Desde quando o Ozempic")
    # O modelo escreveu com espaço fino inseparável (U+202F) entre as palavras: além da data por
    # extenso, foi isso que derrubou a comparação de string do verificador da Parte 1.
    assert "\u202f" in resposta and "16 de setembro" not in resposta
    assert "16 de setembro" in avaliadores.normalizar(resposta)
    assert avaliadores.deterministico(resposta, _caso("G11").esperado)["valor_esperado"] is True


def test_falso_positivo_da_parte1_linagliptina_agora_falha():
    resposta = _resposta_real_da_parte1("Linagliptina 5mg genérica tem desconto de PBM na Drogasil")
    props = avaliadores.deterministico(resposta, _caso("G13").esperado)
    assert props["sem_proibidos"] is False  # "Não há registro" com o produto cadastrado


def test_respostas_reais_de_preco_passam():
    resposta = _resposta_real_da_parte1("preço de tabela da Trayenta 5mg na Araujo")
    assert avaliadores.passou(avaliadores.deterministico(resposta, _caso("G01").esperado))


# ------------------------------------------------------------ determinístico
def test_normalizar_tira_markdown_e_nbsp():
    assert avaliadores.normalizar("**R$ 322,15**") == "r$ 322,15"


def test_pbm_rotulado():
    esperado = {"pbm_valor": ["215,87"]}
    assert avaliadores.deterministico("Preço PBM: R$ 215,87", esperado)["pbm_rotulado"] is True
    longe = "O preço na farmácia é R$ 215,87 hoje." + " x" * 60 + " (sem programa de desconto)"
    assert avaliadores.deterministico(longe, esperado)["pbm_rotulado"] is False


def test_nao_como_palavra_inteira():
    esperado = {"valores": [["não"]]}
    assert avaliadores.deterministico("Não, não pode.", esperado)["valor_esperado"] is True
    assert avaliadores.deterministico("Pode sim, sem restrição.", esperado)["valor_esperado"] is False


def test_sem_preco_e_sem_quantidade():
    esperado = {"sem_preco": True, "sem_quantidade": True}
    props = avaliadores.deterministico("Foram 40 caixas a R$ 13,81.", esperado)
    assert props["sem_preco_inventado"] is False and props["sem_quantidade_inventada"] is False
    props = avaliadores.deterministico("Não tenho dados de vendas.", esperado)
    assert props["sem_preco_inventado"] and props["sem_quantidade_inventada"]


def test_propriedade_nao_aplicavel_e_none():
    props = avaliadores.deterministico("qualquer", {})
    assert set(props.values()) == {None}


# ---------------------------------------------------------------- trajetória
def _chamada(nome, **args):
    return {"tipo": "chamada_ferramenta", "ferramenta": nome, "argumentos": args, "resultado": {}}


def test_trajetoria_cobertura_superfluas_ordem():
    esperado = {"ferramentas_obrigatorias": ["consultar_precos", "exportar_analise"],
                "ordem": ["consultar_precos", "exportar_analise"]}
    certa = [_chamada("consultar_precos", produto="x"), _chamada("exportar_analise", pergunta="p")]
    assert avaliadores.trajetoria(certa, esperado) == {"cobertura": True, "sem_superfluas": True, "ordem": True}
    invertida = list(reversed(certa))
    assert avaliadores.trajetoria(invertida, esperado)["ordem"] is False


def test_chamada_identica_repetida_e_superflua():
    t = [_chamada("consultar_precos", produto="x"), _chamada("consultar_precos", produto="x")]
    assert avaliadores.trajetoria(t, {})["sem_superfluas"] is False
    t = [_chamada("consultar_precos", produto="x"), _chamada("consultar_precos", produto="y")]
    assert avaliadores.trajetoria(t, {})["sem_superfluas"] is True


def test_ferramenta_proibida():
    t = [_chamada("consultar_precos", produto="x"), _chamada("exportar_analise", pergunta="p")]
    assert avaliadores.trajetoria(t, {"ferramentas_proibidas": ["exportar_analise"]})["sem_superfluas"] is False


# ------------------------------------------------------------------ resultado
def test_resultado_conta_exportacoes():
    assert avaliadores.resultado(1, {"exportacoes": 1}, "resposta_final")["exportacoes"] is True
    assert avaliadores.resultado(2, {"exportacoes": 1}, "resposta_final")["exportacoes"] is False
    assert avaliadores.resultado(0, {}, "orcamento_excedido_passos")["terminou_com_resposta"] is False


def test_executar_caso_mede_estado_do_mundo(tmp_path, monkeypatch):
    """A avaliação de resultado conta o arquivo que a ferramenta REALMENTE criou — não o que a
    resposta diz ter feito."""
    from src.evals import suite
    from src.projects.farmacia_precos import tools_farmacia

    monkeypatch.setattr(suite, "PASTA_EXECUCOES", RAIZ / "logs" / "_teste_tmp")
    original = tools_farmacia.PASTA_EXPORTS

    class AgenteQueMente:
        def executar(self, pergunta, orcamento):
            # Diz que salvou, mas não chama a ferramenta.
            return SimpleNamespace(resposta_final="Salvei a análise. R$ 13,63.", motivo_terminacao="resposta_final",
                                   trajetoria=[_chamada("consultar_precos", produto="Novalgina")],
                                   orcamento=SimpleNamespace(tokens_usados=10))

    try:
        r = executar_caso(AgenteQueMente(), _caso("G17"), "teste", 1)
        assert r["exportacoes_criadas"] == 0
        assert r["propriedades"]["exportacoes"] is False
        assert r["propriedades"]["cobertura"] is False
        assert r["passou"] is False
    finally:
        tools_farmacia.PASTA_EXPORTS = original
        import shutil
        shutil.rmtree(RAIZ / "logs" / "_teste_tmp", ignore_errors=True)


# ---------------------------------------------------------- agregação e regra
def _reg(cid, classe, ok, props=None):
    return {"caso_id": cid, "classe": classe, "passou": ok, "propriedades": props or {}}


def test_taxas_e_pass_k():
    regs = [_reg("a", "x", True), _reg("a", "x", False), _reg("b", "y", True), _reg("b", "y", True)]
    assert taxa(regs) == 0.75
    assert taxas_por_classe(regs) == {"x": 0.5, "y": 1.0}
    assert pass_k(regs) == {"a": False, "b": True}
    assert propriedade_pass_k([_reg("a", "x", True, {"p": True}), _reg("a", "x", True, {"p": None})], "p")


def test_regra_promove_so_acima_do_ruido():
    criticas_ok = {"classe recusa": True}
    d = regra.aplicar(0.70, 0.80, ruido_pp=4.0, taxas_classe_a={"x": 0.7}, taxas_classe_b={"x": 0.8}, pass_k_criticas_b=criticas_ok)
    assert d.promover  # +10 >= max(8, 5)
    d = regra.aplicar(0.70, 0.76, ruido_pp=4.0, taxas_classe_a={"x": 0.7}, taxas_classe_b={"x": 0.76}, pass_k_criticas_b=criticas_ok)
    assert not d.promover  # +6 < 8


def test_regra_barra_regressao_de_classe_mesmo_com_media_subindo():
    d = regra.aplicar(0.60, 0.80, ruido_pp=0.0, taxas_classe_a={"x": 0.5, "y": 1.0},
                      taxas_classe_b={"x": 1.0, "y": 0.5}, pass_k_criticas_b={"c": True})
    assert not d.promover and "y caiu 50.0" in d.motivos[1]


def test_regra_barra_falha_critica():
    d = regra.aplicar(0.5, 0.9, 0.0, {"x": 0.5}, {"x": 0.9}, {"classe recusa": False})
    assert not d.promover


# ------------------------------------------------------------------ juiz
def test_concordancia_ignora_rotulo_vazio():
    linhas = [
        {"veredito_juiz": "sim", "rotulo_humano": "sim"},
        {"veredito_juiz": "nao", "rotulo_humano": "não"},
        {"veredito_juiz": "sim", "rotulo_humano": "nao"},
        {"veredito_juiz": "sim", "rotulo_humano": ""},
    ]
    c = concordancia(linhas)
    assert c.n == 3 and c.juiz_sim_humano_nao == 1 and abs(c.taxa - 2 / 3) < 1e-9
    assert not c.adotado  # menos de 30 rótulos nunca adota
