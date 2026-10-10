"""As três estratégias de corte do Exercício 6 (Aula 06, nota 02).

Parâmetros e justificativas:

- `TAMANHO_CARACTERES = 1200` e `SOBREPOSICAO = 200`: é a decisão da v1 do grupo
  (exercicios/aula-06-base-de-conhecimento.md §4: "300 tokens com overlap de 50"), convertida
  para caracteres a ~4 caracteres por token em português. Medir a v1 é o objetivo: as seções do
  corpus têm de 83 a 419 caracteres (mediana 205), então um bloco de 1.200 junta de 3 a 6
  seções — inclusive regra geral e exceção no mesmo vetor. Os 200 de sobreposição cobrem uma
  frase de exceção típica do corpus (~100–150 caracteres) cortada na borda de um bloco.
- Corte por estrutura: a unidade natural do corpus é a seção `##` (artigo de política, item de
  FAQ, verbete de glossário). Cada trecho **herda o título do documento e da seção** — um artigo
  que diz "dos artigos 1 e 2" sem o título não faz sentido sozinho (Aula 06, nota 02).
  Seções acima de `MAXIMO_ESTRUTURA` caracteres seriam quebradas por parágrafo; no corpus atual
  nenhuma passa disso, e o limite existe só para um documento novo não gerar um trecho gigante.

Os cortes por caracteres operam sobre o corpo cru do documento, sem herdar cabeçalho: é a
estratégia ingênua, e herdar cabeçalho nela já seria parte do corte por estrutura.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .corpus import Documento

TAMANHO_CARACTERES = 1200
SOBREPOSICAO = 200
MAXIMO_ESTRUTURA = 1500

ESTRATEGIAS = ("caracteres", "caracteres+overlap", "estrutura")


@dataclass(frozen=True)
class Trecho:
    """Unidade indexada. `id` é o identificador que o agente cita, e que o código confere."""

    id: str
    doc_id: str
    texto: str
    secao: str
    metadados: dict = field(default_factory=dict, hash=False, compare=False)


def _metadados_do_documento(doc: Documento) -> dict:
    return {
        "doc_id": doc.id,
        "titulo": doc.titulo,
        "tipo": doc.tipo,
        "versao": doc.versao,
        "vigente_desde": doc.vigente_desde,
        "revogado_em": doc.revogado_em,
    }


def _janelas(texto: str, tamanho: int, passo: int) -> list[str]:
    if tamanho <= 0 or passo <= 0:
        raise ValueError("tamanho e passo precisam ser positivos")
    pedacos = []
    inicio = 0
    while inicio < len(texto):
        pedacos.append(texto[inicio : inicio + tamanho])
        if inicio + tamanho >= len(texto):
            break
        inicio += passo
    return pedacos


def cortar_por_caracteres(doc: Documento, tamanho: int = TAMANHO_CARACTERES) -> list[Trecho]:
    meta = _metadados_do_documento(doc)
    return [
        Trecho(id=f"{doc.id}#c{i:02d}", doc_id=doc.id, texto=p, secao="", metadados=meta)
        for i, p in enumerate(_janelas(doc.corpo, tamanho, tamanho), start=1)
    ]


def cortar_com_sobreposicao(
    doc: Documento, tamanho: int = TAMANHO_CARACTERES, sobreposicao: int = SOBREPOSICAO
) -> list[Trecho]:
    if not 0 <= sobreposicao < tamanho:
        raise ValueError("a sobreposição precisa ser menor que o tamanho do bloco")
    meta = _metadados_do_documento(doc)
    return [
        Trecho(id=f"{doc.id}#o{i:02d}", doc_id=doc.id, texto=p, secao="", metadados=meta)
        for i, p in enumerate(_janelas(doc.corpo, tamanho, tamanho - sobreposicao), start=1)
    ]


def _secoes(corpo: str) -> list[tuple[str, str]]:
    """Divide o corpo em (titulo_da_secao, texto) pelos cabeçalhos `## `. O texto antes do
    primeiro `##` (o `#` do título e a introdução) vira a seção "Introdução"."""
    partes = re.split(r"^## +(.+)$", corpo, flags=re.MULTILINE)
    secoes = []
    introducao = re.sub(r"^# .+$", "", partes[0], flags=re.MULTILINE).strip()
    if introducao:
        secoes.append(("Introdução", introducao))
    for titulo, texto in zip(partes[1::2], partes[2::2]):
        secoes.append((titulo.strip(), texto.strip()))
    return secoes


def cortar_por_estrutura(doc: Documento, maximo: int = MAXIMO_ESTRUTURA) -> list[Trecho]:
    meta = _metadados_do_documento(doc)
    trechos: list[Trecho] = []
    for i, (secao, texto) in enumerate(_secoes(doc.corpo), start=1):
        cabecalho = f"{doc.titulo} — {secao}\n\n"
        if len(texto) <= maximo:
            blocos = [texto]
        else:
            blocos = [p.strip() for p in texto.split("\n\n") if p.strip()]
        for j, bloco in enumerate(blocos, start=1):
            sufixo = "" if len(blocos) == 1 else f".{j}"
            trechos.append(
                Trecho(
                    id=f"{doc.id}#s{i:02d}{sufixo}",
                    doc_id=doc.id,
                    texto=cabecalho + bloco,
                    secao=secao,
                    metadados={**meta, "secao": secao},
                )
            )
    return trechos


def cortar(doc: Documento, estrategia: str) -> list[Trecho]:
    if estrategia == "caracteres":
        return cortar_por_caracteres(doc)
    if estrategia == "caracteres+overlap":
        return cortar_com_sobreposicao(doc)
    if estrategia == "estrutura":
        return cortar_por_estrutura(doc)
    raise ValueError(f"estratégia desconhecida: {estrategia!r} (válidas: {', '.join(ESTRATEGIAS)})")


def cortar_corpus(docs: list[Documento], estrategia: str) -> list[Trecho]:
    return [t for doc in docs for t in cortar(doc, estrategia)]
