"""O contrato do sistema com quem o usa (Parte 2, §1): a entrada é TEXTO, a saída é um objeto
validado.

Três campos da saída são obrigatórios pelo enunciado, com os nomes deste case:

- `resultado`    — a resposta ao gestor (ou a pergunta de volta, ou a recusa);
- `fontes`       — o que sustenta o resultado, conferível: a linha da view do banco de preços,
                   o trecho do corpus com identificador, ou a ferramenta que respondeu;
- `suficiencia`  — se o sistema teve base para responder. A recusa é parte do contrato: uma
                   saída `insuficiente` é uma saída válida, não uma exceção.

`suficiencia` é decidida em CÓDIGO (`src/grafo/nos.py::montar_saida`), nunca pelo modelo: o
modelo diria "suficiente" com a mesma fluência com que inventa um número.

O que acompanha o texto sem ser digitado por ninguém (§1.1) é declarado em `Entrada`:
`usuario_id` (matrícula pseudônima do gestor, vem da sessão do sistema interno) e `sessao_id`
(a aba de chat). Os dois compõem o `thread_id` do checkpoint (§5.5).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

MAX_CARACTERES_ENTRADA = 800  # ~200 tokens: o teto do "objetivo" no orçamento da janela (docs/memoria.md §1.2)


class Entrada(BaseModel):
    texto: str = Field(description="O que o gestor digitou, exatamente como digitou.")
    usuario_id: str = Field(default="G-0000", pattern=r"^[A-Za-z0-9_-]{1,40}$", description="Matrícula pseudônima do gestor (da sessão do sistema interno).")
    sessao_id: str = Field(default="s1", pattern=r"^[A-Za-z0-9_-]{1,40}$", description="Identificador da conversa (aba de chat).")

    @property
    def thread_id(self) -> str:
        return f"{self.usuario_id}:{self.sessao_id}"


class Fonte(BaseModel):
    tipo: Literal["banco_precos", "corpus", "ferramenta"]
    referencia: str = Field(description="Conferível: view+filtro do banco, id do trecho do corpus, ou nome da ferramenta.")
    detalhe: str = Field(default="", description="O que a fonte devolveu, resumido (data da coleta, título do documento...).")


class AcaoExecutada(BaseModel):
    acao: str
    argumentos: dict
    chave_idempotencia: str
    ja_existia: bool
    resultado: dict


class SaidaAgente(BaseModel):
    resultado: str = Field(description="A resposta, a pergunta de volta ou a recusa — o texto que o gestor lê.")
    fontes: list[Fonte] = Field(default_factory=list)
    suficiencia: Literal["suficiente", "insuficiente", "aguardando_esclarecimento", "aguardando_aprovacao"]
    motivo_insuficiencia: str | None = None
    suposicoes: list[str] = Field(default_factory=list, description="Escolhas que o sistema fez no lugar do gestor, declaradas.")
    pergunta_esclarecimento: str | None = None
    acoes_executadas: list[AcaoExecutada] = Field(default_factory=list)
    alertas: list[str] = Field(default_factory=list, description="Citação inválida, ferramenta com erro, etc.")
    motivo_terminacao: str
    thread_id: str
    turno: int


# ------------------------------------------------------------------ contratos internos
class Triagem(BaseModel):
    """Saída estruturada do nó `triagem`. `rota` é `Literal`: o schema garante que a resposta é uma
    das rotas válidas — NÃO garante que é a rota certa (isso é medido em scripts/avaliar_triagem.py)."""

    rota: Literal["atender", "esclarecer", "fora_escopo"]
    pilar: Literal["preco", "regra", "vendas_estoque", "misto", "nenhum"]
    pergunta_reescrita: str = Field(description="A pergunta completa e autocontida, já combinada com a conversa.")
    faltando: list[str] = Field(default_factory=list)
    pergunta_esclarecimento: str | None = None
    suposicoes: list[str] = Field(default_factory=list)
    justificativa: str = ""

    @field_validator("pergunta_esclarecimento")
    @classmethod
    def _vazia_vira_none(cls, v: str | None) -> str | None:
        return v.strip() or None if v else None


class DecisaoHumana(BaseModel):
    """O que a pessoa devolve no ponto de parada (§8.2)."""

    decisao: Literal["aprovar", "rejeitar", "editar", "expirou"]
    argumentos: dict | None = Field(default=None, description="Só com decisao='editar': os argumentos corrigidos (parciais).")
    revisor: str = "nao-informado"
    comentario: str = ""
