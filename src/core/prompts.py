"""Prompts versionados em arquivo (Aula 03, nota 03; Parte 2, §2.2).

Formato do arquivo: tudo antes do heading `## Prompt enviado ao modelo` é documentação
(técnica, contrato de saída, o que cada frase impede); o texto depois dele é o que vai para a
API. A versão é lida da linha `**Versão:** vX.Y` — e entra no carimbo de toda execução, porque
o `git log` diz como o arquivo mudou, não qual versão estava rodando numa execução.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

PASTA_PROMPTS = Path(__file__).resolve().parents[1] / "prompts"
MARCADOR = "## Prompt enviado ao modelo"


@dataclass(frozen=True)
class PromptVersionado:
    nome: str
    versao: str
    texto: str
    caminho: Path

    @property
    def rotulo(self) -> str:
        return f"{self.nome}@{self.versao}"

    def preencher(self, **valores: str) -> str:
        """Substitui marcadores `{{nome}}`. Marcador sem valor é erro: um prompt enviado com
        `{{contexto}}` literal produz resposta sem base, e sem nenhum aviso."""
        texto = self.texto
        for chave, valor in valores.items():
            texto = texto.replace("{{" + chave + "}}", valor)
        restantes = re.findall(r"\{\{(\w+)\}\}", texto)
        if restantes:
            raise ValueError(f"{self.rotulo}: marcadores sem valor: {', '.join(sorted(set(restantes)))}")
        return texto


def carregar_prompt(nome: str, pasta: Path = PASTA_PROMPTS) -> PromptVersionado:
    caminho = pasta / f"{nome}.md"
    conteudo = caminho.read_text(encoding="utf-8")
    # Só conta o heading de linha inteira: a documentação do próprio arquivo costuma CITAR o
    # marcador ("tudo antes do heading ## Prompt enviado ao modelo..."), e dividir na primeira
    # ocorrência mandaria a documentação para o modelo como se fosse prompt.
    partes = re.split(rf"^{re.escape(MARCADOR)}[ \t]*$", conteudo, maxsplit=1, flags=re.MULTILINE)
    if len(partes) != 2:
        raise ValueError(f"{caminho} não tem o heading '{MARCADOR}' numa linha própria.")
    documentacao, texto = partes
    achado = re.search(r"\*\*Versão:\*\*\s*(v[\w.]+)", documentacao)
    if not achado:
        raise ValueError(f"{caminho} não declara '**Versão:** vX.Y' na documentação.")
    return PromptVersionado(nome=nome, versao=achado.group(1), texto=texto.strip(), caminho=caminho)
