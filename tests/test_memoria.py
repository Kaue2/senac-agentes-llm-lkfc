"""Testes determinísticos da memória (Exercício 8): sem rede e sem LLM."""

from __future__ import annotations

import json
import re
from datetime import date

import numpy as np
import pytest

from src.memoria.contexto import montar_contexto_memoria
from src.memoria.memoria import Memoria
from src.memoria.politica import (
    RecorteExtraido,
    extrair_preferencia_farmacia,
    extrair_recorte,
    mascarar_sensiveis,
    texto_para_memoria,
)
from src.rag.embeddings import EmbeddingComCache, ModeloEmbedding


class EmbeddingFalso(ModeloEmbedding):
    nome = "falso:bow"
    VOCAB = ["trayenta", "ozempic", "drogasil", "raia", "preço", "ruptura", "atual", "falta"]

    def _embed(self, textos):
        linhas = []
        for t in textos:
            palavras = re.findall(r"\w+", t.lower())
            v = np.array([palavras.count(w) for w in self.VOCAB], dtype=np.float32) + 1e-3
            linhas.append(v / np.linalg.norm(v))
        return np.array(linhas, dtype=np.float32)


@pytest.fixture
def memoria(tmp_path):
    emb = EmbeddingComCache(EmbeddingFalso(), caminho=tmp_path / "cache.db")
    m = Memoria(emb, pasta=tmp_path / "memoria")
    yield m
    m.fechar()


RECORTE = RecorteExtraido(("consultar_precos",), ("Trayenta 5mg",), ("Drogasil",), ("atual",), "resposta_final")


# ---------------------------------------------------------------- política
def test_mascara_cpf_email_telefone():
    texto = "cliente 123.456.789-09, ana@x.com.br, (11) 98765-4321 comprou"
    mascarado = mascarar_sensiveis(texto)
    assert "123.456" not in mascarado and "ana@" not in mascarado and "98765" not in mascarado
    assert "[CPF]" in mascarado and "[EMAIL]" in mascarado and "[TELEFONE]" in mascarado


def test_texto_para_memoria_trunca():
    assert len(texto_para_memoria("x" * 500)) == 200


def test_recorte_guarda_argumentos_e_nunca_o_resultado():
    trajetoria = [
        {"tipo": "chamada_ferramenta", "ferramenta": "consultar_precos",
         "argumentos": {"produto": "Trayenta 5mg", "farmacia": "Drogasil", "modo": "atual"},
         "resultado": {"resultados": [{"PrecoFarmacia": 322.15}]}},
        {"tipo": "resposta_final", "conteudo": "R$ 322,15"},
    ]
    recorte = extrair_recorte(trajetoria, "resposta_final")
    assert recorte.produtos == ("Trayenta 5mg",) and recorte.farmacias == ("Drogasil",)
    assert "322" not in json.dumps(recorte.__dict__)


@pytest.mark.parametrize("frase, esperado", [
    ("minha farmácia padrão é a Drogasil", "Drogasil"),
    ("A partir de hoje minha farmacia padrao passa a ser Raia.", "Raia"),
    ("qual o preço na Drogasil?", None),
])
def test_extrai_preferencia_so_quando_declarada(frase, esperado):
    assert extrair_preferencia_farmacia(frase) == esperado


# ---------------------------------------------------------- idempotência
def test_episodio_idempotente_pelo_conteudo(memoria):
    a = memoria.gravar_episodio("G-0042", "2026-10-01", "preço da Trayenta?", RECORTE)
    b = memoria.gravar_episodio("G-0042", "2026-10-01", "preço da Trayenta?", RECORTE)
    assert (a.ja_existia, b.ja_existia) == (False, True)
    assert a.id == b.id and memoria.contar_episodios() == 1


def test_fato_idempotente_e_exige_carimbo(memoria):
    a = memoria.gravar_fato("usuario:G-1:farmacia_padrao", "Drogasil", "2026-09-10", "teste")
    b = memoria.gravar_fato("usuario:G-1:farmacia_padrao", "Drogasil", "2026-09-10", "teste")
    assert not a.ja_existia and b.ja_existia
    with pytest.raises(ValueError, match="valido_desde"):
        memoria.gravar_fato("usuario:G-1:x", "y", "", "teste")


# ------------------------------------------------------------ contradição
def test_contradicao_desempata_por_data_e_registra_descarte(memoria):
    chave = "usuario:G-1:farmacia_padrao"
    memoria.gravar_fato(chave, "Raia", "2026-10-01", "teste")      # gravado primeiro, mais novo
    memoria.gravar_fato(chave, "Drogasil", "2026-09-10", "teste")  # gravado depois, mais antigo
    leitura = memoria.ler_fato(chave)
    assert leitura.vencedor.valor == "Raia"
    assert [f.valor for f in leitura.descartados] == ["Drogasil"]
    descartes = memoria.caminho_descartes.read_text(encoding="utf-8")
    assert "Drogasil" in descartes and "max(valido_desde)" in descartes
    assert memoria.contar_chaves() == 1  # contradição não apaga


# -------------------------------------------------------------- busca
def test_episodios_filtrados_por_usuario_e_ordenados(memoria):
    memoria.gravar_episodio("G-1", "2026-10-01", "ruptura do Ozempic", RecorteExtraido(("consultar_precos",), ("Ozempic",), (), ("ruptura",), "ok"))
    memoria.gravar_episodio("G-1", "2026-10-01", "preço da Trayenta", RECORTE)
    memoria.gravar_episodio("G-2", "2026-10-01", "preço da Trayenta", RECORTE)
    eps = memoria.buscar_episodios("G-1", "preço atual da Trayenta", k=2)
    assert [e.usuario_id for e in eps] == ["G-1", "G-1"]
    assert "Trayenta" in eps[0].texto


# ---------------------------------------------------------- esquecimento
def test_decaimento_remove_episodio_antigo(memoria):
    memoria.gravar_episodio("G-1", "2026-01-01", "antigo", RECORTE)
    memoria.gravar_episodio("G-1", "2026-09-30", "recente", RECORTE)
    assert memoria.decair(date(2026, 10, 9), dias=90) == 1
    assert memoria.contar_episodios() == 1


def test_remover_registro_muda_e_restaura_comportamento(memoria):
    contexto_vazio = montar_contexto_memoria(memoria, "G-1", "preço da Trayenta").texto
    g = memoria.gravar_fato("usuario:G-1:farmacia_padrao", "Drogasil", "2026-10-01", "teste")
    assert "Drogasil" in montar_contexto_memoria(memoria, "G-1", "preço da Trayenta").texto
    assert memoria.remover_registro(g.id)
    assert montar_contexto_memoria(memoria, "G-1", "preço da Trayenta").texto == contexto_vazio


def test_remocao_por_titular_alcanca_todas_as_estruturas(memoria, tmp_path):
    titular = "G-0042"
    memoria.gravar_episodio(titular, "2026-10-01", "preço da Trayenta", RECORTE)
    memoria.gravar_fato(f"usuario:{titular}:farmacia_padrao", "Drogasil", "2026-09-10", "teste")
    memoria.gravar_fato(f"usuario:{titular}:farmacia_padrao", "Raia", "2026-10-01", "teste")
    memoria.ler_fato(f"usuario:{titular}:farmacia_padrao")  # gera registro de descarte
    memoria.gravar_regra(f"Quando {titular} pedir preço, mostre só PrecoFarmacia.", autor="bi")
    memoria.gravar_regra("Cite sempre a data da coleta.", autor="bi")
    checkpoints = tmp_path / "checkpoints"
    checkpoints.mkdir()
    (checkpoints / "x.json").write_text(json.dumps({"usuario_id": titular, "outro": "mantém"}, ensure_ascii=False), encoding="utf-8")

    assert memoria.varrer(titular, [checkpoints, memoria.pasta])  # antes: está em todo lugar
    relatorio = memoria.remover_titular(titular, [checkpoints])
    assert relatorio["episodica"] == 1 and relatorio["semantica"] == 2 and relatorio["procedural"] == 1
    assert memoria.varrer(titular, [checkpoints, memoria.pasta]) == []  # inclusive nos bytes do .db
    assert "Cite sempre a data da coleta." in memoria.texto_procedural()  # regra geral fica
    assert "mantém" in (checkpoints / "x.json").read_text(encoding="utf-8")  # redigido, não apagado


def test_remocao_tira_o_vetor_do_cache_de_embeddings(memoria, tmp_path):
    import sqlite3
    memoria.gravar_episodio("G-9", "2026-10-01", "preço da Trayenta", RECORTE)
    contar = lambda: sqlite3.connect(tmp_path / "cache.db").execute("SELECT COUNT(*) FROM cache").fetchone()[0]
    antes = contar()
    memoria.remover_titular("G-9", [])
    assert contar() == antes - 1


# ------------------------------------------------------------ teto da janela
def test_contexto_respeita_teto_descartando_episodio(memoria):
    memoria.gravar_fato("usuario:G-1:farmacia_padrao", "Drogasil", "2026-10-01", "teste")
    for i in range(3):
        memoria.gravar_episodio("G-1", "2026-10-01", f"preço da Trayenta {i} " + "detalhe " * 40, RECORTE)
    contexto = montar_contexto_memoria(memoria, "G-1", "preço da Trayenta", teto=150)
    assert contexto.tokens <= 150
    assert "Drogasil" in contexto.texto  # o fato semântico nunca é o descartado
    assert contexto.descartados_por_teto >= 1
