"""Política de escrita da memória (Exercício 8, §3 e §4): o que entra, o que NÃO entra, e quem
decide.

Política escolhida: **o código extrai por regra** (nunca o agente decide o que guardar), com
**correção humana** sobre a memória semântica. Preço declarado: perde o que a regra não previu.
Foi preferida a "o agente decide" porque, neste case, o que o agente produziria para guardar é
justamente o que não pode entrar — números de preço (deriváveis e que envelhecem em um dia) e
texto gerado por ele mesmo (não verificado).

Volume por execução (medido em scripts/aula08_memoria.py): 1 registro episódico de até
`MAX_CARACTERES_PERGUNTA` + recorte estruturado; 0 ou 1 fato semântico (só se o gestor declarar
uma preferência explicitamente); 0 regras procedurais (só humanos escrevem).

O que NÃO entra, e por quê (a lista que vale mais que a de inclusão):

| Não entra | Por quê |
|---|---|
| preço, ruptura, qualquer número devolvido por ferramenta | derivável do banco e envelhece em 24 h (a coleta é diária): guardar é dívida e vira resposta velha com aparência de memória |
| a resposta em texto livre do agente | gerada pelo modelo, não verificada; memória é durável e o que entra nela sai muitas vezes (Aula 14) |
| trechos do RAG | deriváveis do corpus, que tem curadoria própria (revogação por metadado) |
| CPF, e-mail, telefone digitados na pergunta | dado pessoal que não precisa persistir; mascarado ANTES de gravar |
| nome de paciente, receita, dado de PBM | o case nunca trata dado de paciente (docs/case.md §9; corpus programas-pbm) |
| credenciais, connection string, chave de API | segredo — nunca sai do .env |
| identificador do gestor em texto claro dentro de regra procedural | regra procedural vale para todos; regra "do gestor X" é preferência, e vai para a semântica, onde a remoção alcança por chave |
"""

from __future__ import annotations

import re
from dataclasses import dataclass

MAX_CARACTERES_PERGUNTA = 200

_PADROES_SENSIVEIS = [
    (re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b"), "[CPF]"),
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b"), "[EMAIL]"),
    (re.compile(r"\(?\b\d{2}\)?\s?9?\d{4}-?\d{4}\b"), "[TELEFONE]"),
]

# Declaração explícita de preferência: "minha farmácia padrão é a Drogasil".
_PREFERENCIA_FARMACIA = re.compile(
    r"minha farm[aá]cia padr[aã]o (?:agora )?(?:[eé]|passa a ser|ser[aá]) (?:a )?([A-ZÀ-Ú][\wÀ-ú ]+?)(?:[.,;!?]|$)",
    re.IGNORECASE,
)


def mascarar_sensiveis(texto: str) -> str:
    for padrao, substituto in _PADROES_SENSIVEIS:
        texto = padrao.sub(substituto, texto)
    return texto


def texto_para_memoria(pergunta: str) -> str:
    """Pergunta como ela pode ser gravada: mascarada e truncada."""
    return mascarar_sensiveis(pergunta.strip())[:MAX_CARACTERES_PERGUNTA]


@dataclass(frozen=True)
class RecorteExtraido:
    ferramentas: tuple[str, ...]
    produtos: tuple[str, ...]
    farmacias: tuple[str, ...]
    modos: tuple[str, ...]
    terminou_por: str


def extrair_recorte(trajetoria: list[dict], motivo_terminacao: str) -> RecorteExtraido:
    """Regra de extração do episódio: só o RECORTE da consulta (o que foi perguntado ao banco),
    nunca o RESULTADO (o que o banco respondeu)."""
    chamadas = [p for p in trajetoria if p.get("tipo") == "chamada_ferramenta"]

    def coletar(campo: str) -> tuple[str, ...]:
        return tuple(sorted({str(c["argumentos"][campo]) for c in chamadas if c.get("argumentos", {}).get(campo)}))

    return RecorteExtraido(
        ferramentas=tuple(c["ferramenta"] for c in chamadas),
        produtos=coletar("produto"),
        farmacias=coletar("farmacia"),
        modos=coletar("modo"),
        terminou_por=motivo_terminacao,
    )


def extrair_preferencia_farmacia(pergunta: str) -> str | None:
    achado = _PREFERENCIA_FARMACIA.search(pergunta)
    return achado.group(1).strip() if achado else None
