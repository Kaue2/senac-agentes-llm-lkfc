"""O grafo do agente de BI (Parte 2, §6): `StateGraph` montado UMA vez e compilado com checkpointer.

O desenho em ASCII, a tabela de padrões e a conferência contra este código estão em
docs/arquitetura.md e docs/grafo.md; `conferir_grafo.py` (raiz) importa `obter_grafo` daqui —
o mesmo objeto que src/main.py executa.

Decisão que o framework transformou em parâmetro (§6.6): `RECURSION_LIMIT`. No LangGraph 1.2.16
o padrão é `DEFAULT_RECURSION_LIMIT = 10007` (sobrescrevível pela variável de ambiente
`LANGGRAPH_DEFAULT_RECURSION_LIMIT`); nas versões 0.x era 25. A mudança já aconteceu: com 25, um
turno de 8 passos com aprovação (≈ 26 supersteps) estouraria; com 10007, um laço que escape dos
nossos tetos rodaria ~5 mil voltas antes de parar. Por isso o valor é declarado aqui, derivado do
teto de passos, e não herdado da biblioteca.
"""

from __future__ import annotations

import sqlite3
from functools import lru_cache
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from . import nos
from .dependencias import Dependencias
from .estado import EstadoGrafo
from .rotas import rota_agente, rota_entrada, rota_ferramentas, rota_humano, rota_triagem

PASTA_RAIZ = Path(__file__).resolve().parents[2]
CAMINHO_CHECKPOINTS = PASTA_RAIZ / "dados" / "checkpoints" / "grafo.db"

# Supersteps de um turno: entrada (1) + ramos paralelos (1) + portão (1) + 2 por passo do laço
# (agente, ferramentas) + aprovação (preparar, aguardar, exportar = 3) + saída e memória (2).
# Com AGENT_MAX_STEPS=8: 1+1+1+16+3+2 = 24. O teto de passos (código) dispara antes; este limite é
# a rede de segurança para um defeito no próprio grafo, com folga de ~2x.
RECURSION_LIMIT = 50


def _sem_schema(rota):
    """A rota sem a anotação de tipo: o LangGraph inferiria o schema dela, e o mesmo desenho
    compilado com outro estado (scripts/demo_reducer.py) teria dois tipos para o mesmo canal."""
    return lambda estado: rota(estado)


def construir_grafo(estado_cls: type = EstadoGrafo) -> StateGraph:
    """`estado_cls` é parâmetro só para scripts/demo_reducer.py, que compila o MESMO desenho com um
    estado sem reducer para mostrar o que se perde. O sistema usa sempre `EstadoGrafo`."""
    g = StateGraph(estado_cls, context_schema=Dependencias)

    def no(nome, funcao):
        # input_schema explícito: sem ele o LangGraph lê o schema da anotação `estado: EstadoGrafo`
        # do nó, e o grafo com outro estado (demo_reducer) teria dois tipos para o mesmo canal.
        g.add_node(nome, funcao, input_schema=estado_cls)

    no("receber_entrada", nos.receber_entrada)
    no("carregar_memoria", nos.carregar_memoria)
    no("triagem", nos.triagem)
    no("portao", nos.portao)
    no("esclarecer", nos.esclarecer)
    no("recusar", nos.recusar)
    no("agente", nos.agente)
    no("ferramentas", nos.ferramentas)
    no("preparar_aprovacao", nos.preparar_aprovacao)
    no("aguardar_humano", nos.aguardar_humano)
    no("exportar", nos.exportar)
    no("montar_saida", nos.montar_saida)
    no("gravar_memoria", nos.gravar_memoria)

    g.add_edge(START, "receber_entrada")
    g.add_conditional_edges("receber_entrada", _sem_schema(rota_entrada),
                            {"carregar_memoria": "carregar_memoria", "triagem": "triagem", "montar_saida": "montar_saida"})
    g.add_edge(["carregar_memoria", "triagem"], "portao")  # junção: espera os dois ramos
    g.add_conditional_edges("portao", _sem_schema(rota_triagem), {"agente": "agente", "esclarecer": "esclarecer", "recusar": "recusar"})
    g.add_edge("esclarecer", "montar_saida")
    g.add_edge("recusar", "montar_saida")
    g.add_conditional_edges("agente", _sem_schema(rota_agente), {"ferramentas": "ferramentas", "montar_saida": "montar_saida"})
    g.add_conditional_edges("ferramentas", _sem_schema(rota_ferramentas), {"preparar_aprovacao": "preparar_aprovacao", "agente": "agente"})
    g.add_edge("preparar_aprovacao", "aguardar_humano")
    g.add_conditional_edges("aguardar_humano", _sem_schema(rota_humano),
                            {"exportar": "exportar", "agente": "agente", "montar_saida": "montar_saida", "aguardar_humano": "aguardar_humano"})
    g.add_edge("exportar", "agente")
    g.add_edge("montar_saida", "gravar_memoria")
    g.add_edge("gravar_memoria", END)
    return g


def abrir_checkpointer(caminho: Path = CAMINHO_CHECKPOINTS) -> SqliteSaver:
    """Checkpoint em ARQUIVO (SQLite), não em memória: a aprovação pendente sobrevive ao fim do
    processo, e a conversa continua amanhã com o mesmo `thread_id`."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(caminho, check_same_thread=False)
    conn.execute("PRAGMA secure_delete = ON")  # remoção por titular (docs/memoria.md §5.4)
    return SqliteSaver(conn)


@lru_cache(maxsize=None)
def obter_grafo(caminho_checkpoints: Path = CAMINHO_CHECKPOINTS):
    """O grafo compilado — uma vez por processo e por arquivo de checkpoint."""
    return construir_grafo().compile(checkpointer=abrir_checkpointer(caminho_checkpoints))


def config_da_thread(thread_id: str, checkpoint_id: str | None = None) -> dict:
    configurable = {"thread_id": thread_id}
    if checkpoint_id:
        configurable["checkpoint_id"] = checkpoint_id
    return {"configurable": configurable, "recursion_limit": RECURSION_LIMIT}
