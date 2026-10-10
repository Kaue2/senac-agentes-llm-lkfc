"""Carrega o prompt de sistema versionado de prompts/analista_bi_v1.md.

Só o texto depois do heading "## Prompt enviado ao modelo" vai para a API — o resto do
arquivo é documentação (carimbo de versão, técnica usada, contrato de saída — ver
docs/01-primeira-entrega.md, item 4.3).
"""

from __future__ import annotations

import re

from .config import CAMINHO_PROMPT

_MARCADOR = "## Prompt enviado ao modelo"


def carregar_prompt_sistema() -> str:
    texto = CAMINHO_PROMPT.read_text(encoding="utf-8")
    # Heading de linha inteira, não a primeira ocorrência da frase (ver src/core/prompts.py).
    partes = re.split(rf"^{re.escape(_MARCADOR)}[ \t]*$", texto, maxsplit=1, flags=re.MULTILINE)
    if len(partes) != 2:
        raise RuntimeError(f"{CAMINHO_PROMPT} não tem o heading '{_MARCADOR}' numa linha própria.")
    return partes[1].strip()
