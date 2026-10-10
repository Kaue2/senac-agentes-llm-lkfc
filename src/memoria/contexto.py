"""A memória como fonte da janela de contexto, com teto próprio (Exercício 8, §1.2).

A memória de longo prazo compete com o system prompt, a pergunta, a trajetória e os trechos do
RAG. Teto da memória: `TETO_TOKENS_MEMORIA = 600` (o orçamento das cinco fontes está em
docs/memoria.md). Quando estoura, descarta-se primeiro o episódio MENOS relevante — nunca o
fato semântico (é curto e é o que muda o comportamento) nem a regra procedural (é instrução).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import tiktoken

from .memoria import Memoria

TETO_TOKENS_MEMORIA = 600
K_EPISODIOS = 3
_CODIFICADOR = tiktoken.get_encoding("o200k_base")


def contar_tokens(texto: str) -> int:
    return len(_CODIFICADOR.encode(texto))


@dataclass
class ContextoMemoria:
    texto: str
    tokens: int
    fatos: dict[str, str] = field(default_factory=dict)
    episodios: list[str] = field(default_factory=list)
    descartados_por_teto: int = 0
    descartes_por_contradicao: int = 0


def montar_contexto_memoria(memoria: Memoria, usuario_id: str, pergunta: str, teto: int = TETO_TOKENS_MEMORIA) -> ContextoMemoria:
    blocos: list[str] = []
    resultado = ContextoMemoria(texto="", tokens=0)

    procedural = memoria.texto_procedural()
    if procedural:
        blocos.append("Regras do time de BI para conduzir a análise:\n" + procedural)

    for chave in memoria.chaves_do_usuario(usuario_id):
        leitura = memoria.ler_fato(chave)
        if leitura.vencedor:
            resultado.fatos[chave] = leitura.vencedor.valor
            resultado.descartes_por_contradicao += len(leitura.descartados)
    if resultado.fatos:
        linhas = [f"- {c.split(':', 2)[2]}: {v}" for c, v in resultado.fatos.items()]
        blocos.append(
            "Preferências declaradas por este gestor (use como recorte padrão quando a pergunta não "
            "disser o contrário; diga na resposta que usou a preferência):\n" + "\n".join(linhas)
        )

    episodios = memoria.buscar_episodios(usuario_id, pergunta, k=K_EPISODIOS)
    texto_base = "\n\n".join(blocos)
    linhas_ep: list[str] = []
    for ep in episodios:  # já em ordem de relevância: o último a entrar é o primeiro a sair
        candidata = f"- [{ep.data}] {ep.texto}"
        cabecalho = "Consultas anteriores deste gestor (só o recorte, sem os números — reconsulte os dados):\n"
        tentativa = "\n\n".join(filter(None, [texto_base, cabecalho + "\n".join(linhas_ep + [candidata])]))
        if contar_tokens(tentativa) > teto:
            resultado.descartados_por_teto += 1
            continue
        linhas_ep.append(candidata)
        resultado.episodios.append(ep.id)

    if linhas_ep:
        blocos.append("Consultas anteriores deste gestor (só o recorte, sem os números — reconsulte os dados):\n" + "\n".join(linhas_ep))
    resultado.texto = "\n\n".join(blocos)
    resultado.tokens = contar_tokens(resultado.texto) if resultado.texto else 0
    return resultado
