"""Leitura do corpus de conhecimento (dados/corpus/*.md).

Cada documento traz um cabeçalho de metadados entre `---` (ver dados/corpus/README.md). Os
metadados não vão para o vetor: eles existem para filtro (`tipo`, `revogado_em`) e para o
desempate de anterioridade (`vigente_desde`), que o vetor não representa — a cegueira de
TEMPO da Aula 07 (nota 02, §5).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

PASTA_CORPUS = Path(__file__).resolve().parents[2] / "dados" / "corpus"

_CAMPOS_OBRIGATORIOS = ("id", "titulo", "tipo", "versao", "vigente_desde", "revogado_em", "dono")


@dataclass(frozen=True)
class Documento:
    id: str
    titulo: str
    tipo: str
    versao: str
    vigente_desde: str
    revogado_em: str | None
    dono: str
    corpo: str
    caminho: Path

    @property
    def vigente(self) -> bool:
        return not self.revogado_em


def normalizar_espacos(texto: str) -> str:
    """Colapsa quebras de linha e espaços repetidos. Usado para comparar trechos com
    evidências: o Markdown quebra parágrafos em várias linhas, e a quebra não é conteúdo."""
    return re.sub(r"\s+", " ", texto).strip()


def ler_documento(caminho: Path) -> Documento:
    texto = caminho.read_text(encoding="utf-8")
    if not texto.startswith("---\n"):
        raise ValueError(f"{caminho.name}: falta o cabeçalho de metadados entre '---'.")
    _, cabecalho, corpo = texto.split("---\n", 2)

    metadados: dict[str, str] = {}
    for linha in cabecalho.strip().splitlines():
        chave, _, valor = linha.partition(":")
        metadados[chave.strip()] = valor.strip()

    faltando = [c for c in _CAMPOS_OBRIGATORIOS if c not in metadados]
    if faltando:
        raise ValueError(f"{caminho.name}: metadados ausentes: {', '.join(faltando)}")
    if metadados["id"] != caminho.stem:
        raise ValueError(f"{caminho.name}: id '{metadados['id']}' difere do nome do arquivo.")

    return Documento(
        id=metadados["id"],
        titulo=metadados["titulo"],
        tipo=metadados["tipo"],
        versao=metadados["versao"],
        vigente_desde=metadados["vigente_desde"],
        revogado_em=metadados["revogado_em"] or None,
        dono=metadados["dono"],
        corpo=corpo.strip(),
        caminho=caminho,
    )


def carregar_corpus(pasta: Path = PASTA_CORPUS) -> list[Documento]:
    """Todos os documentos da pasta, em ordem de nome (ordem estável = índice reprodutível).
    O README.md da pasta é documentação do corpus, não conteúdo — fica de fora."""
    return [ler_documento(p) for p in sorted(pasta.glob("*.md")) if p.name != "README.md"]
