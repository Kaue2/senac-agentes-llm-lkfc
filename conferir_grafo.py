"""Conferência do grafo contra o desenho (Parte 2, §6.4).

Importa o MESMO objeto que src/main.py executa (`src.grafo.grafo.obter_grafo`) — não monta um
grafo próprio — e imprime os nós e as arestas. A saída é colada em docs/arquitetura.md ao lado do
desenho; se divergirem, vale o código.

Uso: python conferir_grafo.py
"""

from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8")

from src.grafo.grafo import RECURSION_LIMIT, obter_grafo  # noqa: E402


def main() -> None:
    grafo = obter_grafo()
    desenho = grafo.get_graph()

    print("NÓS")
    for nome in desenho.nodes:
        print(f"  {nome}")

    print("\nARESTAS  (? = condicional)")
    for aresta in desenho.edges:
        marca = "?" if aresta.conditional else " "
        print(f"  {marca} {aresta.source} -> {aresta.target}")

    print(f"\nrecursion_limit declarado: {RECURSION_LIMIT}")
    print(f"checkpointer: {type(grafo.checkpointer).__name__}")


if __name__ == "__main__":
    main()
