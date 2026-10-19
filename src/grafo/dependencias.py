"""O que os nós do grafo usam e que NÃO é estado: cliente do modelo, ferramentas, banco, memória,
prompts, tetos e relógio.

Entra no grafo pelo `context` do LangGraph (`grafo.invoke(..., context=deps)`), e não pelo estado:
nada disto é serializável no checkpoint, e nada disto muda durante uma execução. Isso é o que
permite compilar o grafo UMA vez (`src/grafo/grafo.py::obter_grafo`) e reaproveitá-lo com outro
modelo, outro banco ou um relógio falso nos testes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from src.core.prompts import PromptVersionado, carregar_prompt
from src.core.tools import RegistroFerramentas


@dataclass(frozen=True)
class Tetos:
    """Os quatro tetos da Aula 05. O LangGraph só cobre o de passos (`recursion_limit`), e o cobre
    mal: conta supersteps, não chamadas ao modelo. Os quatro abaixo são verificados em código, no
    nó `agente`, antes de cada chamada (docs/grafo.md §6)."""

    max_passos: int = 8            # chamadas ao modelo no laço, por turno
    max_tokens: int = 20000        # soma de tokens do turno (triagem + laço)
    max_segundos: float = 90.0     # relógio de parede do turno
    max_custo_reais: float = 0.0   # 0 = sem teto (tier gratuito); verificado se > 0
    limite_repeticao: int = 2      # mesma ferramenta + mesmos argumentos: na 3ª vez é laço
    prazo_aprovacao_horas: float = 24.0

    @classmethod
    def do_ambiente(cls) -> "Tetos":
        return cls(
            max_passos=int(os.environ.get("AGENT_MAX_STEPS", "8")),
            max_tokens=int(os.environ.get("AGENT_MAX_TOKENS", "20000")),
            max_segundos=float(os.environ.get("AGENT_MAX_SECONDS", "90")),
            prazo_aprovacao_horas=float(os.environ.get("AGENT_PRAZO_APROVACAO_HORAS", "24")),
        )


def agora_utc() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Dependencias:
    cliente: Any                      # openai.OpenAI ou um falso com a mesma interface
    modelo: str
    ferramentas: RegistroFerramentas
    prompt_agente: PromptVersionado
    prompt_triagem: PromptVersionado
    fonte_dados: str = "desconhecida"
    memoria: Any | None = None        # src.memoria.memoria.Memoria; None = sem memória de longo prazo
    tetos: Tetos = field(default_factory=Tetos)
    agora: Callable[[], datetime] = agora_utc

    def carimbo(self) -> dict[str, str]:
        """A combinação em uso, gravada no início de toda execução (§2.2)."""
        return {
            "modelo": self.modelo,
            "prompt_agente": self.prompt_agente.rotulo,
            "prompt_triagem": self.prompt_triagem.rotulo,
            "fonte_dados": self.fonte_dados,
            "memoria": "ativa" if self.memoria is not None else "desligada",
            "tetos": f"passos={self.tetos.max_passos} tokens={self.tetos.max_tokens} "
                     f"segundos={self.tetos.max_segundos:g} repeticao={self.tetos.limite_repeticao} "
                     f"prazo_aprovacao_h={self.tetos.prazo_aprovacao_horas:g}",
        }


def carregar_prompts() -> tuple[PromptVersionado, PromptVersionado]:
    return carregar_prompt("analista_bi_v3"), carregar_prompt("triagem_v1")
