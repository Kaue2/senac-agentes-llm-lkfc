"""Registro de ferramentas do agente — genérico, sem nada específico de um projeto.

Cada projeto (ver src/projects/<nome>/tools_*.py) registra suas próprias ferramentas
aqui, com um schema JSON (o que o modelo vê) e um handler Python (o que roda de verdade).
O registro também guarda os metadados que docs/case.md §2.4 pede na tabela de ferramentas:
leitura/escrita, reversível, e contra o que ela conversa.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class Ferramenta:
    nome: str
    descricao: str
    parametros_json_schema: dict
    handler: Callable[..., dict]
    leitura_ou_escrita: str  # "leitura" | "escrita"
    reversivel: bool
    conversa_com: str

    def schema_para_modelo(self) -> dict:
        """Formato esperado pela API de tool calling (compatível com a lib openai)."""
        return {
            "type": "function",
            "function": {
                "name": self.nome,
                "description": self.descricao,
                "parameters": self.parametros_json_schema,
            },
        }


class RegistroFerramentas:
    def __init__(self) -> None:
        self._ferramentas: dict[str, Ferramenta] = {}

    def registrar(self, ferramenta: Ferramenta) -> None:
        self._ferramentas[ferramenta.nome] = ferramenta

    def schemas_para_modelo(self) -> list[dict]:
        return [f.schema_para_modelo() for f in self._ferramentas.values()]

    def chamar(self, nome: str, argumentos: dict) -> dict:
        """Executa a ferramenta. Erro de ferramenta vira DADO (dict com "erro"), nunca exceção
        que derruba o laço — é o contrato pedido em docs/01-primeira-entrega.md, item 4.1."""
        ferramenta = self._ferramentas.get(nome)
        if ferramenta is None:
            return {"erro": f"ferramenta '{nome}' não existe", "ferramentas_disponiveis": list(self._ferramentas)}
        try:
            return ferramenta.handler(**argumentos)
        except Exception as exc:  # ferramenta de terceiro pode falhar de formas imprevisíveis
            return {"erro": f"falha ao executar '{nome}': {exc}"}

    def tabela_de_ferramentas(self) -> list[dict[str, Any]]:
        """Para gerar a tabela de docs/case.md §2.4 a partir do código, não escrita à mão duas vezes."""
        return [
            {
                "ferramenta": f.nome,
                "o_que_faz": f.descricao,
                "leitura_ou_escrita": f.leitura_ou_escrita,
                "reversivel": f.reversivel,
                "conversa_com": f.conversa_com,
            }
            for f in self._ferramentas.values()
        ]
