"""Monta o agente deste projeto: liga o núcleo genérico (src/core) às peças específicas
de farmácia (banco, ferramentas, prompt). Um projeto novo replica só este arquivo.

Duas versões, comparadas pela suíte do Exercício 11:
- `v1` — o agente da Parte 1: prompt `src/prompts/analista_bi_v1.md`, 4 ferramentas.
- `v2` — v1 + `consultar_base_conhecimento` (RAG como ferramenta) e o prompt
  `src/prompts/analista_bi_v2.md`, que difere da v1 por uma única regra.
"""

from __future__ import annotations

from src.core.agent import Agente
from src.core.llm_client import ConfiguracaoModelo, criar_cliente
from src.core.prompts import carregar_prompt
from src.core.tools import RegistroFerramentas

from .db import BancoPrecos
from .system_prompt import carregar_prompt_sistema
from .tools_farmacia import registrar_ferramentas_farmacia

VERSOES = ("v1", "v2")


def montar_agente_com_config(
    config_modelo: ConfiguracaoModelo, banco: BancoPrecos | None = None, versao: str = "v1"
) -> tuple[Agente, BancoPrecos]:
    """Monta um agente para uma configuração de modelo explícita — usado por
    scripts/compare_models.py (três candidatos, mesmo banco/ferramentas/prompt) e pela suíte
    do Exercício 11 (mesmo modelo, versões diferentes)."""
    if versao not in VERSOES:
        raise ValueError(f"versão desconhecida: {versao!r} (válidas: {', '.join(VERSOES)})")
    cliente = criar_cliente(config_modelo)
    banco = banco or BancoPrecos()

    registro = RegistroFerramentas()
    registrar_ferramentas_farmacia(registro, banco)

    if versao == "v1":
        prompt_sistema = carregar_prompt_sistema()
    else:
        # Import tardio: a v1 não deve exigir o modelo de embedding (~2 GB) para rodar.
        from src.rag.embeddings import modelo_do_ambiente
        from src.rag.indice import PASTA_INDICES, IndiceVetorial

        from .tools_conhecimento import registrar_ferramenta_conhecimento

        indice = IndiceVetorial.carregar(PASTA_INDICES / "estrutura.db")
        registrar_ferramenta_conhecimento(registro, indice, modelo_do_ambiente())
        prompt_sistema = carregar_prompt("analista_bi_v2").texto

    agente = Agente(cliente, config_modelo.modelo, registro, prompt_sistema)
    return agente, banco


def montar_agente(versao: str = "v1") -> tuple[Agente, BancoPrecos, ConfiguracaoModelo]:
    """Monta o agente com o modelo ATIVO (LLM_BASE_URL/LLM_MODEL/OPENAI_API_KEY) —
    o que src/main.py e scripts/run_demo_cases.py realmente usam."""
    config_modelo = ConfiguracaoModelo.do_ambiente()
    agente, banco = montar_agente_com_config(config_modelo, versao=versao)
    return agente, banco, config_modelo


def exigir_espelho(banco: BancoPrecos) -> None:
    """Trava dos scripts de exercício e de avaliação: eles gravam logs versionados e comparam com
    valores esperados tirados do espelho sintético. Contra o banco real do cliente, o primeiro
    vazaria dado comercial de terceiro para o repositório (docs/case.md §9) e o segundo compararia
    preço real com gabarito sintético."""
    if banco.fonte != "espelho_sqlite":
        banco.close()
        raise SystemExit(
            f"Fonte de dados '{banco.fonte}': os scripts de exercício só rodam no espelho sintético. "
            "Rode com FRACTALPRECOS_CONNECTION_STRING= (vazia) no ambiente."
        )
