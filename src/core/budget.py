"""Orçamento e condições de parada do agente.

Genérico: qualquer projeto usa a mesma régua de passos/tokens/dinheiro,
só muda os valores (vindos do .env de cada projeto).
"""

from __future__ import annotations

from dataclasses import dataclass


class OrcamentoExcedidoError(Exception):
    """Levantado quando o laço deveria parar por causa do orçamento, não por ter terminado a tarefa."""


@dataclass
class Orcamento:
    max_passos: int
    max_tokens: int
    max_custo_reais: float = 0.0  # 0.0 = sem teto de custo (ex.: modelo gratuito)

    passos_usados: int = 0
    tokens_usados: int = 0
    custo_usado_reais: float = 0.0

    def registrar_passo(self, tokens_do_passo: int, custo_do_passo: float = 0.0) -> None:
        self.passos_usados += 1
        self.tokens_usados += tokens_do_passo
        self.custo_usado_reais += custo_do_passo

    def excedeu_passos(self) -> bool:
        return self.passos_usados >= self.max_passos

    def excedeu_tokens(self) -> bool:
        return self.tokens_usados >= self.max_tokens

    def excedeu_custo(self) -> bool:
        return self.max_custo_reais > 0 and self.custo_usado_reais >= self.max_custo_reais

    def motivo_se_excedido(self) -> str | None:
        if self.excedeu_passos():
            return f"orcamento_excedido_passos ({self.passos_usados}/{self.max_passos})"
        if self.excedeu_tokens():
            return f"orcamento_excedido_tokens ({self.tokens_usados}/{self.max_tokens})"
        if self.excedeu_custo():
            return f"orcamento_excedido_custo (R${self.custo_usado_reais:.4f}/R${self.max_custo_reais:.4f})"
        return None
