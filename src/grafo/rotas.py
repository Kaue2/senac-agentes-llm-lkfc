"""As arestas condicionais do grafo. TODAS são regra em código (o degrau mais barato, §6.3): leem
um campo que um nó já escreveu. O único julgamento sobre texto livre — "esta mensagem é atendível,
está incompleta ou está fora do escopo?" — é feito pelo MODELO dentro do nó `triagem`, com saída
`Literal`; a aresta só lê o campo `triagem.rota`.

Funções de rota não escrevem no estado (o LangGraph descarta o que elas devolveriam): por isso o
motivo de término é gravado pelo nó, e a rota só o lê.
"""

from __future__ import annotations

from .estado import EstadoGrafo


def rota_entrada(estado: EstadoGrafo) -> list[str] | str:
    """Quem decide: CÓDIGO (campo `motivo_terminacao` preenchido por `receber_entrada`)."""
    if estado.get("motivo_terminacao"):
        return "montar_saida"
    return ["carregar_memoria", "triagem"]  # paralelização (sectioning): dois ramos independentes


def rota_triagem(estado: EstadoGrafo) -> str:
    """Quem decide: MODELO escolhe `triagem.rota` (Literal); CÓDIGO aplica o limite de UMA pergunta
    de esclarecimento por pergunta do gestor (docs/case.md §2: evitar o vaivém)."""
    t = estado["triagem"]
    if t["rota"] == "atender":
        return "agente"
    if t["rota"] == "fora_escopo":
        return "recusar"
    if estado.get("esclarecimentos_feitos", 0) >= 1:
        return "recusar"
    return "esclarecer"


def rota_agente(estado: EstadoGrafo) -> str:
    """Quem decide: CÓDIGO. O modelo pediu ferramenta → `ferramentas`; respondeu, estourou teto,
    entrou em laço ou falhou → `montar_saida` (o nó `agente` já gravou o motivo)."""
    if estado.get("motivo_terminacao"):
        return "montar_saida"
    return "ferramentas"


def rota_ferramentas(estado: EstadoGrafo) -> str:
    """Quem decide: CÓDIGO (`acao_pendente` não-nulo = o modelo pediu a ferramenta de escrita)."""
    return "preparar_aprovacao" if estado.get("acao_pendente") else "agente"


def rota_humano(estado: EstadoGrafo) -> str:
    """Quem decide: a PESSOA (o valor devolvido ao `interrupt`), lido em CÓDIGO."""
    decisao = (estado.get("decisao_humana") or {}).get("decisao")
    if decisao in ("aprovar", "editar"):
        return "exportar"
    if decisao == "rejeitar":
        return "agente"
    if decisao == "expirou":
        return "montar_saida"
    return "aguardar_humano"  # resposta inválida: pausa de novo, com o mesmo pedido
