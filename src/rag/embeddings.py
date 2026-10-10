"""Modelos de embedding — o campo "modelo de embedding" do carimbo (Aula 06, §6).

Provedor escolhido por `EMBEDDING_PROVIDER` no .env:

- `local` (padrão): modelo ONNX via fastembed, na CPU, sem chave de API. O grupo não tem verba
  de API (docs/modelos.md) e o provedor de LLM escolhido (Groq) não oferece embedding.
  O modelo padrão é `intfloat/multilingual-e5-large`, escolhido por MEDIÇÃO e não por ranking
  (exercicios/aula-06-buscador-do-regulamento.md, desafio A): nas 20 perguntas do conjunto, com
  corte por estrutura, recall@1 de 88% contra 62% do MiniLM-L12 e 56% do mpnet-base, e foi o
  único dos três em que algum limiar de distância separou as perguntas sem resposta das com
  resposta. O preço: ~2,2 GB de download e indexação lenta na CPU (minutos, uma vez — o cache
  abaixo evita repetir). `EMBEDDING_MODEL_LOCAL` troca o modelo (ex.: o MiniLM, ~220 MB, para
  máquina fraca) — e trocar o modelo invalida o limiar do portão, que precisa ser recalibrado.
- `mistral`: `mistral-embed`, o modelo dos laboratórios, pela API compatível com a OpenAI.
  Exige `MISTRAL_API_KEY`.

A família e5 foi treinada com prefixos: `query: ` na pergunta e `passage: ` no trecho. Sem eles
a qualidade cai — por isso o protocolo separa `embed_consultas` de `embed_documentos`.

Os vetores saem normalizados (norma 1): cosseno vira produto interno, e a distância do portão é
`1 - cosseno`, a métrica dos laboratórios.

Cache em disco por (modelo, sha256 do texto já com prefixo): reindexar o mesmo corpus com o
mesmo modelo não recalcula nada, e trocar de modelo nunca reaproveita vetor de outro.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
from pathlib import Path

import numpy as np

CAMINHO_CACHE = Path(__file__).resolve().parents[2] / "dados" / "cache" / "embeddings.db"
MODELO_LOCAL_PADRAO = "intfloat/multilingual-e5-large"

_PREFIXOS_E5 = ("query: ", "passage: ")


def _normalizar(matriz: np.ndarray) -> np.ndarray:
    normas = np.linalg.norm(matriz, axis=1, keepdims=True)
    normas[normas == 0] = 1.0
    return (matriz / normas).astype(np.float32)


class ModeloEmbedding:
    """Base: subclasses implementam `_embed` (textos já prefixados → matriz normalizada)."""

    nome: str = ""
    prefixo_consulta: str = ""
    prefixo_documento: str = ""

    def _embed(self, textos: list[str]) -> np.ndarray:
        raise NotImplementedError

    def embed_consultas(self, textos: list[str]) -> np.ndarray:
        return self._embed([self.prefixo_consulta + t for t in textos])

    def embed_documentos(self, textos: list[str]) -> np.ndarray:
        return self._embed([self.prefixo_documento + t for t in textos])


class EmbeddingLocal(ModeloEmbedding):
    def __init__(self, modelo: str = MODELO_LOCAL_PADRAO) -> None:
        from fastembed import TextEmbedding

        self.nome = f"fastembed:{modelo}"
        if "e5" in modelo.lower():
            self.prefixo_consulta, self.prefixo_documento = _PREFIXOS_E5
        self._modelo = TextEmbedding(model_name=modelo)

    def _embed(self, textos: list[str]) -> np.ndarray:
        return _normalizar(np.array(list(self._modelo.embed(textos)), dtype=np.float32))


class EmbeddingMistral(ModeloEmbedding):
    # Lotes de 32: a API limita tokens por requisição; os trechos do corpus têm até ~150
    # tokens, e 32 × 150 fica com folga abaixo do limite.
    TAMANHO_LOTE = 32

    def __init__(self, modelo: str = "mistral-embed") -> None:
        from openai import OpenAI

        chave = os.environ.get("MISTRAL_API_KEY", "")
        if not chave:
            raise RuntimeError("EMBEDDING_PROVIDER=mistral exige MISTRAL_API_KEY no .env.")
        self.nome = f"mistral:{modelo}"
        self._modelo = modelo
        self._cliente = OpenAI(base_url="https://api.mistral.ai/v1", api_key=chave)

    def _embed(self, textos: list[str]) -> np.ndarray:
        vetores: list[list[float]] = []
        for i in range(0, len(textos), self.TAMANHO_LOTE):
            resposta = self._cliente.embeddings.create(model=self._modelo, input=textos[i : i + self.TAMANHO_LOTE])
            vetores.extend(item.embedding for item in resposta.data)
        return _normalizar(np.array(vetores, dtype=np.float32))


class EmbeddingComCache(ModeloEmbedding):
    """Envolve um modelo com o cache em disco; mesmo nome e mesmos prefixos do envolvido."""

    def __init__(self, modelo: ModeloEmbedding, caminho: Path = CAMINHO_CACHE) -> None:
        self.nome = modelo.nome
        self.prefixo_consulta = modelo.prefixo_consulta
        self.prefixo_documento = modelo.prefixo_documento
        self._modelo = modelo
        self._caminho_cache = caminho
        caminho.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(caminho)
        # secure_delete: DELETE no SQLite só marca a página como livre, e o conteúdo apagado
        # continua legível no arquivo. A remoção por titular (Exercício 8) precisa que ele suma.
        self._conn.execute("PRAGMA secure_delete = ON")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS cache (modelo TEXT, hash TEXT, vetor BLOB, PRIMARY KEY (modelo, hash))"
        )

    @staticmethod
    def _hash(texto: str) -> str:
        return hashlib.sha256(texto.encode("utf-8")).hexdigest()

    def _embed(self, textos: list[str]) -> np.ndarray:
        hashes = [self._hash(t) for t in textos]
        encontrados: dict[str, np.ndarray] = {}
        for h in set(hashes):
            linha = self._conn.execute(
                "SELECT vetor FROM cache WHERE modelo = ? AND hash = ?", (self.nome, h)
            ).fetchone()
            if linha:
                encontrados[h] = np.frombuffer(linha[0], dtype=np.float32)

        faltando = [(h, t) for h, t in dict(zip(hashes, textos)).items() if h not in encontrados]
        if faltando:
            # Os textos já chegam prefixados: chama o `_embed` do envolvido, não o público.
            novos = self._modelo._embed([t for _, t in faltando])
            for (h, _), vetor in zip(faltando, novos):
                encontrados[h] = vetor
                self._conn.execute(
                    "INSERT OR REPLACE INTO cache VALUES (?, ?, ?)", (self.nome, h, vetor.astype(np.float32).tobytes())
                )
            self._conn.commit()
        return np.stack([encontrados[h] for h in hashes])


def modelo_do_ambiente() -> ModeloEmbedding:
    provedor = os.environ.get("EMBEDDING_PROVIDER", "local").strip().lower()
    if provedor == "mistral":
        return EmbeddingComCache(EmbeddingMistral())
    if provedor == "local":
        return EmbeddingComCache(EmbeddingLocal(os.environ.get("EMBEDDING_MODEL_LOCAL", MODELO_LOCAL_PADRAO)))
    raise RuntimeError(f"EMBEDDING_PROVIDER inválido: {provedor!r} (use 'local' ou 'mistral').")
