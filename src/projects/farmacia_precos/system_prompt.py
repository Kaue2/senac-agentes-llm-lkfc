"""Carrega o prompt de sistema versionado de prompts/analista_bi_v1.md.

Só o texto depois do heading "## Prompt enviado ao modelo" vai para a API — o resto do
arquivo é documentação (carimbo de versão, técnica usada, contrato de saída — ver
docs/01-primeira-entrega.md, item 4.3).
"""

from __future__ import annotations

from .config import CAMINHO_PROMPT

_MARCADOR = "## Prompt enviado ao modelo"


def carregar_prompt_sistema() -> str:
    texto = CAMINHO_PROMPT.read_text(encoding="utf-8")
    if _MARCADOR not in texto:
        raise RuntimeError(f"{CAMINHO_PROMPT} não tem o heading '{_MARCADOR}'.")
    return texto.split(_MARCADOR, 1)[1].strip()
