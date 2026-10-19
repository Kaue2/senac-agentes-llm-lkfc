"""Modelo falso com a interface de `openai.OpenAI().chat.completions.create`, para os testes e para
as demonstrações que precisam ser determinísticas (scripts/demo_reducer.py). Respostas roteirizadas:
uma fila para a triagem (chamadas com `response_format`) e outra para o laço do agente."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from types import SimpleNamespace


def resposta(content: str | None = None, tool_calls: list | None = None, tokens: int = 100) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=tool_calls))],
        usage=SimpleNamespace(total_tokens=tokens),
    )


def chamada(nome: str, argumentos: dict, id_: str = "c1") -> SimpleNamespace:
    return SimpleNamespace(id=id_, function=SimpleNamespace(name=nome, arguments=json.dumps(argumentos, ensure_ascii=False)))


def triagem_json(rota: str = "atender", **extra) -> SimpleNamespace:
    base = {"rota": rota, "pilar": "preco", "pergunta_reescrita": "pergunta", "faltando": [],
            "pergunta_esclarecimento": None, "suposicoes": [], "justificativa": "roteiro"}
    base.update(extra)
    return resposta(json.dumps(base))


@dataclass
class ModeloFalso:
    triagens: list = field(default_factory=list)
    passos: list = field(default_factory=list)
    chamadas_agente: int = 0
    recebidas: list = field(default_factory=list)

    def __post_init__(self) -> None:
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        if kwargs.get("response_format"):
            return self.triagens.pop(0)
        self.chamadas_agente += 1
        self.recebidas.append(kwargs["messages"])
        return self.passos.pop(0)
