"""Controles de segurança aplicados no grafo, fora do prompt (Parte 3, docs/seguranca.md §2).

C2 — validação da saída do modelo antes de usá-la (`validar_exportacao`), chamada pelo nó
`ferramentas` ANTES de criar o pedido de aprovação. Mitiga ASI01/ASI09: um texto injetado (na
pergunta, ou num campo raspado do site de uma farmácia que volta na ferramenta de preço) pode
levar o modelo a pedir a exportação de uma análise com um número inventado; o revisor humano, que
confia no sistema, aprovaria. Com o controle, o pedido nem chega ao revisor.

Fail-closed: qualquer exceção dentro da validação conta como bloqueio.
"""

from __future__ import annotations

import json
import re

LIMITE_EXPORTACOES_POR_TURNO = 1
MAX_CARACTERES_CAMPO = 4000
_NUMERO = re.compile(r"\d+[.,]\d{2}(?!\d)")


def _normalizar(numero: str) -> str:
    return f"{float(numero.replace(',', '.')):.2f}"


def numeros_devolvidos(trajetoria: list[dict]) -> set[str]:
    """Os números com casas decimais que as ferramentas devolveram NESTE turno."""
    numeros: set[str] = set()

    def coletar(valor) -> None:
        if isinstance(valor, bool):
            return
        if isinstance(valor, float):
            numeros.add(f"{valor:.2f}")
        elif isinstance(valor, int):
            numeros.add(f"{valor:.2f}")
        elif isinstance(valor, str):
            numeros.update(_normalizar(n) for n in _NUMERO.findall(valor))
        elif isinstance(valor, dict):
            for v in valor.values():
                coletar(v)
        elif isinstance(valor, list):
            for v in valor:
                coletar(v)

    for passo in trajetoria:
        if passo.get("tipo") == "chamada_ferramenta" and passo.get("ferramenta") != "exportar_analise":
            coletar(passo.get("resultado", {}))
    return numeros


def validar_exportacao(argumentos: dict, trajetoria: list[dict], exportacoes_no_turno: int) -> str | None:
    """Devolve o motivo do bloqueio, ou None se a exportação pode ir para aprovação."""
    try:
        if exportacoes_no_turno >= LIMITE_EXPORTACOES_POR_TURNO:
            return f"limite de {LIMITE_EXPORTACOES_POR_TURNO} exportação por turno atingido"
        for campo in ("pergunta", "dados_resumo", "explicacao"):
            valor = argumentos.get(campo)
            if not isinstance(valor, str) or not valor.strip():
                return f"argumento '{campo}' ausente ou vazio"
            if len(valor) > MAX_CARACTERES_CAMPO:
                return f"argumento '{campo}' com {len(valor)} caracteres (máximo {MAX_CARACTERES_CAMPO})"
        citados = {_normalizar(n) for n in _NUMERO.findall(argumentos["dados_resumo"] + " " + argumentos["explicacao"])}
        sem_origem = sorted(citados - numeros_devolvidos(trajetoria))
        if sem_origem:
            return f"valores sem origem em nenhuma ferramenta deste turno: {', '.join(sem_origem)}"
        return None
    except Exception as exc:  # fail-closed
        return f"falha na validação ({type(exc).__name__}): bloqueado por segurança — {json.dumps(str(exc))[:120]}"
