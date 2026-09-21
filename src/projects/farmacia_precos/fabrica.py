"""Monta o agente deste projeto: liga o núcleo genérico (src/core) às peças específicas
de farmácia (banco, ferramentas, prompt). Um projeto novo replica só este arquivo."""

from __future__ import annotations

from src.core.agent import Agente
from src.core.llm_client import ConfiguracaoModelo, criar_cliente
from src.core.tools import RegistroFerramentas

from .db import BancoPrecos
from .system_prompt import carregar_prompt_sistema
from .tools_farmacia import registrar_ferramentas_farmacia


def montar_agente_com_config(config_modelo: ConfiguracaoModelo, banco: BancoPrecos | None = None) -> tuple[Agente, BancoPrecos]:
    """Monta um agente para uma configuração de modelo explícita — usado por
    scripts/compare_models.py para rodar os três candidatos de docs/modelos.md com o
    mesmo banco/ferramentas/prompt, variando só o modelo."""
    cliente = criar_cliente(config_modelo)
    banco = banco or BancoPrecos()

    registro = RegistroFerramentas()
    registrar_ferramentas_farmacia(registro, banco)

    prompt_sistema = carregar_prompt_sistema()
    agente = Agente(cliente, config_modelo.modelo, registro, prompt_sistema)
    return agente, banco


def montar_agente() -> tuple[Agente, BancoPrecos, ConfiguracaoModelo]:
    """Monta o agente com o modelo ATIVO (LLM_BASE_URL/LLM_MODEL/OPENAI_API_KEY) —
    o que src/main.py e scripts/run_demo_cases.py realmente usam."""
    config_modelo = ConfiguracaoModelo.do_ambiente()
    agente, banco = montar_agente_com_config(config_modelo)
    return agente, banco, config_modelo
