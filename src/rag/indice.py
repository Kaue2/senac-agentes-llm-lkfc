"""O índice vetorial do case: SQLite (trechos, metadados, vetores) + busca exata em numpy.

Por que não um banco vetorial dedicado (pgvector, FAISS, Chroma): o corpus tem 12 documentos e
dá de 19 a 68 trechos conforme a estratégia de corte. A Aula 06 (nota 04) mediu que, nessa
ordem de grandeza, um banco vetorial perde para uma matriz numpy — busca exata sobre algumas
centenas de vetores leva microssegundos, e índice aproximado (HNSW/IVF) só compensa a partir de
dezenas de milhares. O que o case precisa de um "banco de vetores" é persistência, metadado
filtrável e carimbo do índice; o SQLite dá os três sem servidor. A troca vira necessária se o
corpus passar de ~50 mil trechos (ver exercicios/aula-06-base-de-conhecimento-v2.md §3).

Filtro de metadado é aplicado ANTES da similaridade (pré-filtro): "só documentos vigentes" ou
"só políticas" é `==`, não cosseno (Aula 06, nota 04).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import numpy as np

from .chunking import Trecho
from .embeddings import ModeloEmbedding

PASTA_INDICES = Path(__file__).resolve().parents[2] / "dados" / "indices"
METRICA = "cosseno (distância = 1 - cosseno, vetores normalizados)"


@dataclass(frozen=True)
class Resultado:
    trecho: Trecho
    distancia: float
    posicao: int  # 1 = mais próximo


class IndiceVetorial:
    def __init__(self, trechos: list[Trecho], vetores: np.ndarray, carimbo: dict[str, str]) -> None:
        if len(trechos) != len(vetores):
            raise ValueError("número de trechos e de vetores difere")
        self.trechos = trechos
        self.vetores = vetores.astype(np.float32)
        self.carimbo = carimbo

    @classmethod
    def construir(cls, trechos: list[Trecho], modelo: ModeloEmbedding, estrategia: str) -> "IndiceVetorial":
        vetores = modelo.embed_documentos([t.texto for t in trechos])
        carimbo = {
            "modelo_embedding": modelo.nome,
            "chunking": estrategia,
            "metrica": METRICA,
            "n_trechos": str(len(trechos)),
            "construido_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        return cls(trechos, vetores, carimbo)

    def buscar(
        self,
        vetor_consulta: np.ndarray,
        k: int,
        filtro: Callable[[dict], bool] | None = None,
    ) -> list[Resultado]:
        indices = [i for i, t in enumerate(self.trechos) if filtro is None or filtro(t.metadados)]
        if not indices or k <= 0:
            return []
        candidatos = self.vetores[indices]
        distancias = 1.0 - candidatos @ vetor_consulta.astype(np.float32)
        ordem = np.argsort(distancias, kind="stable")[:k]
        return [
            Resultado(trecho=self.trechos[indices[i]], distancia=float(distancias[i]), posicao=pos)
            for pos, i in enumerate(ordem, start=1)
        ]

    # ---------------------------------------------------------------- persistência
    def salvar(self, caminho: Path) -> None:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.unlink(missing_ok=True)
        with sqlite3.connect(caminho) as conn:
            conn.execute("CREATE TABLE carimbo (chave TEXT PRIMARY KEY, valor TEXT)")
            conn.execute(
                "CREATE TABLE trechos (ordem INTEGER PRIMARY KEY, id TEXT UNIQUE, doc_id TEXT, "
                "secao TEXT, texto TEXT, metadados TEXT, vetor BLOB)"
            )
            conn.executemany("INSERT INTO carimbo VALUES (?, ?)", self.carimbo.items())
            conn.executemany(
                "INSERT INTO trechos VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (i, t.id, t.doc_id, t.secao, t.texto, json.dumps(t.metadados, ensure_ascii=False), v.tobytes())
                    for i, (t, v) in enumerate(zip(self.trechos, self.vetores))
                ],
            )

    @classmethod
    def carregar(cls, caminho: Path) -> "IndiceVetorial":
        if not caminho.exists():
            raise FileNotFoundError(f"{caminho} não existe — rode: python scripts/indexar_corpus.py")
        with sqlite3.connect(caminho) as conn:
            carimbo = dict(conn.execute("SELECT chave, valor FROM carimbo").fetchall())
            linhas = conn.execute(
                "SELECT id, doc_id, secao, texto, metadados, vetor FROM trechos ORDER BY ordem"
            ).fetchall()
        trechos = [
            Trecho(id=i, doc_id=d, texto=tx, secao=s, metadados=json.loads(m)) for i, d, s, tx, m, _ in linhas
        ]
        vetores = np.stack([np.frombuffer(v, dtype=np.float32) for *_, v in linhas])
        return cls(trechos, vetores, carimbo)


def somente_vigentes(metadados: dict) -> bool:
    """Filtro de curadoria: exclui documento revogado. Ver Aula 07 §6 — o vetor não sabe que um
    documento foi revogado; quem sabe é o metadado `revogado_em`."""
    return not metadados.get("revogado_em")
