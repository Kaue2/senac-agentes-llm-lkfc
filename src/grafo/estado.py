"""O estado que atravessa o grafo (Parte 2, §7).

A lista de mensagens NÃO é o estado: decisão, contador e identificador são campos com tipo
declarado. A tabela "campo × quem escreve × quem lê" está em docs/grafo.md §4 e é conferida por
tests/test_grafo.py::test_campos_com_mais_de_um_escritor_tem_reducer.

Reducers (§7.2):

- `acumular_ou_zerar` — campos POR TURNO escritos por mais de um nó (`trajetoria`, `eventos`,
  `mensagens_modelo`, `efeitos_aplicados`). `operator.add` sozinho não serve: o checkpoint é por
  conversa (thread), e um segundo turno herdaria a trajetória do primeiro. O LangGraph não oferece
  "zerar" num canal com reducer — devolver `[]` soma uma lista vazia e não apaga nada —, então o
  nó de entrada envia o marcador `ZERAR` e o reducer recomeça a lista.
- `acumular_conversa` — `mensagens` (texto conversacional da thread inteira). Só acrescenta; o
  corte da janela é feito na LEITURA (`janela_da_conversa`), e não no estado: o checkpoint guarda a
  conversa inteira para auditoria, o modelo vê só o fim dela.

Campos sem reducer têm UM escritor por superstep (ver docs/grafo.md §4). O LangGraph levanta
`InvalidUpdateError` se dois nós do MESMO superstep escreverem num campo sem reducer; entre
supersteps diferentes, a escrita sem reducer sobrescreve em silêncio — a demonstração dos dois
casos está em scripts/demo_reducer.py.
"""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

ZERAR: dict[str, bool] = {"__zerar__": True}


def acumular_ou_zerar(atual: list | None, novo: list | None) -> list:
    atual = atual or []
    novo = novo or []
    if novo and novo[0] == ZERAR:
        return list(novo[1:])
    return atual + list(novo)


def acumular_conversa(atual: list | None, novo: list | None) -> list:
    return (atual or []) + list(novo or [])


class EstadoGrafo(TypedDict, total=False):
    # --- entrada do turno (escrito só por receber_entrada)
    entrada: dict[str, Any]
    turno: int
    inicio_turno: str

    # --- conversa: atravessa turnos dentro da mesma thread
    mensagens: Annotated[list[dict[str, Any]], acumular_conversa]
    esclarecimentos_feitos: int

    # --- escritos pelos dois ramos paralelos (carregar_memoria ‖ triagem)
    contexto_memoria: str
    memoria_usada: dict[str, Any]
    triagem: dict[str, Any]
    eventos: Annotated[list[dict[str, Any]], acumular_ou_zerar]
    trajetoria: Annotated[list[dict[str, Any]], acumular_ou_zerar]

    # --- laço do agente
    mensagens_modelo: Annotated[list[dict[str, Any]], acumular_ou_zerar]
    chamadas_pendentes: list[dict[str, Any]]
    passos: int
    tokens: int

    # --- ponto de parada humano
    acao_pendente: dict[str, Any] | None
    aprovacao: dict[str, Any] | None
    decisao_humana: dict[str, Any] | None
    efeitos_aplicados: Annotated[list[dict[str, Any]], acumular_ou_zerar]

    # --- término
    resposta_texto: str | None
    motivo_terminacao: str | None
    saida: dict[str, Any] | None
    gravacoes_memoria: list[dict[str, Any]]


CAMPOS_POR_TURNO_ACUMULADOS = ("eventos", "trajetoria", "mensagens_modelo", "efeitos_aplicados")
