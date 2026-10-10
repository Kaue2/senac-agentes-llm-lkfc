"""Indexa dados/corpus/ com a configuração escolhida no Exercício 6 e grava o índice em
dados/indices/<estrategia>.db (com o carimbo: modelo de embedding, chunking, métrica).

Uso: python scripts/indexar_corpus.py [--estrategia estrutura]

Rodar de novo sempre que o corpus mudar. O índice é derivado (não versionado): versiona-se o
corpus e esta configuração, não os vetores.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()

from src.rag.chunking import ESTRATEGIAS, cortar_corpus  # noqa: E402
from src.rag.corpus import carregar_corpus  # noqa: E402
from src.rag.embeddings import modelo_do_ambiente  # noqa: E402
from src.rag.indice import PASTA_INDICES, IndiceVetorial  # noqa: E402


def caminho_do_indice(estrategia: str) -> Path:
    return PASTA_INDICES / f"{estrategia.replace('+', '_')}.db"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--estrategia", default="estrutura", choices=ESTRATEGIAS)
    args = parser.parse_args()

    docs = carregar_corpus()
    trechos = cortar_corpus(docs, args.estrategia)
    indice = IndiceVetorial.construir(trechos, modelo_do_ambiente(), args.estrategia)
    destino = caminho_do_indice(args.estrategia)
    indice.salvar(destino)
    print(f"{len(docs)} documentos, {len(trechos)} trechos -> {destino}")
    for chave, valor in indice.carimbo.items():
        print(f"  {chave}: {valor}")


if __name__ == "__main__":
    main()
