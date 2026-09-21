"""Constantes específicas deste projeto (o "adaptador" — ver core/ para o que é genérico)."""

from __future__ import annotations

import os
from pathlib import Path

NOME_PROJETO = "farmacia_precos"
PASTA_RAIZ = Path(__file__).resolve().parents[3]
CAMINHO_PROMPT = PASTA_RAIZ / "prompts" / "analista_bi_v1.md"
PASTA_LOGS = PASTA_RAIZ / "logs"


def max_passos() -> int:
    return int(os.environ.get("AGENT_MAX_STEPS", "8"))


def max_tokens() -> int:
    return int(os.environ.get("AGENT_MAX_TOKENS", "20000"))
