"""Cliente de modelo, genérico para qualquer provedor compatível com a API da OpenAI.

Nenhum projeto específico deveria precisar mexer aqui: trocar de modelo é trocar
LLM_BASE_URL / LLM_MODEL / OPENAI_API_KEY no .env (ver .env.example e docs/modelos.md §3.4).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from openai import OpenAI


@dataclass
class ConfiguracaoModelo:
    base_url: str
    modelo: str
    api_key: str

    @classmethod
    def do_ambiente(cls, prefixo: str = "") -> "ConfiguracaoModelo":
        """Lê a configuração do ambiente.

        Sem prefixo, lê o modelo ATIVO (LLM_BASE_URL/LLM_MODEL/OPENAI_API_KEY) — o que o
        agente realmente usa. Com prefixo (ex.: "GROQ"), lê um dos três candidatos
        avaliados em docs/modelos.md, usados só pelo script de comparação.
        """
        sufixo_base_url = f"{prefixo}_BASE_URL" if prefixo else "LLM_BASE_URL"
        sufixo_modelo = f"{prefixo}_MODEL" if prefixo else "LLM_MODEL"
        sufixo_api_key = f"{prefixo}_API_KEY" if prefixo else "OPENAI_API_KEY"

        base_url = os.environ.get(sufixo_base_url, "")
        modelo = os.environ.get(sufixo_modelo, "")
        api_key = os.environ.get(sufixo_api_key, "")

        faltando = [n for n, v in [(sufixo_base_url, base_url), (sufixo_modelo, modelo), (sufixo_api_key, api_key)] if not v]
        if faltando:
            raise RuntimeError(
                f"Variáveis de ambiente ausentes: {', '.join(faltando)}. Preencha o .env (ver .env.example)."
            )
        return cls(base_url=base_url, modelo=modelo, api_key=api_key)


def criar_cliente(config: ConfiguracaoModelo) -> OpenAI:
    # max_retries=6: o tier gratuito responde 429 quando o limite por minuto estoura, com
    # cabeçalho retry-after; a lib openai espera esse tempo com backoff exponencial antes de
    # tentar de novo. O padrão (2) não basta para as rodadas de avaliação das Aulas 07 e 11,
    # que fazem dezenas de chamadas seguidas.
    return OpenAI(base_url=config.base_url, api_key=config.api_key, max_retries=6)


def cliente_ativo_ou_none() -> tuple[OpenAI | None, str]:
    """Cliente do modelo ATIVO, ou (None, motivo) se o .env não estiver preenchido. Usado pelos
    scripts de exercício que têm partes sem LLM (busca, portão) e partes com LLM (geração):
    sem chave, as primeiras rodam e as segundas declaram que não rodaram."""
    try:
        config = ConfiguracaoModelo.do_ambiente()
    except RuntimeError as exc:
        return None, str(exc)
    return criar_cliente(config), config.modelo
