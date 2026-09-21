"""O laço do agente — genérico, sem nada específico de farmácia/preço/qualquer domínio.

Único ponto do código onde o modelo é chamado (`Agente.executar`, no `while True`
abaixo) — o que segue é o comentário pedido em docs/01-primeira-entrega.md, item 4.3,
para essa etapa: técnica, contrato de saída, e o que cada escolha impede.

- **Técnica:** ReAct simplificado com estado explícito, não few-shot nem CoT longo —
  a tarefa é "escolher ferramenta ou responder", não um raciocínio de vários passos que
  se beneficiasse de exemplos no prompt (esses ficam no prompt do PROJETO, ver
  `prompts/analista_bi_v1.md`, que É few-shot). Em vez de acumular a lista de mensagens
  crua (pergunta, resposta, chamada de ferramenta, resultado, resposta, ...) e reenviar
  tudo a cada passo, o agente reconstrói a mensagem enviada ao modelo a partir de um
  ESTADO compacto (`EstadoAgente`) a cada passo.
- **Contrato de saída:** a cada passo, o modelo OU chama uma ferramenta (`tool_calls`)
  OU devolve texto livre em português tratado como resposta final — nunca os dois, nunca
  nenhum dos dois. Não há um terceiro formato.
- **O que isso impede:** o estado compacto impede que o consumo de tokens cresça sem
  controle a cada chamada de ferramenta (o texto reenviado ao modelo cresce em resumos
  de uma linha, não no JSON bruto do banco a cada passo — ver `EstadoAgente.registrar_resultado`,
  que trunca em 600 caracteres). O contrato de saída binário (ferramenta OU resposta
  final) impede a ambiguidade de "o modelo respondeu, mas também queria chamar algo" —
  o laço decide se terminou olhando um único campo (`tool_calls`), não interpretando texto.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from openai import OpenAI

from .budget import Orcamento
from .tools import RegistroFerramentas


@dataclass
class EstadoAgente:
    pergunta_original: str
    resumo_resultados: list[str] = field(default_factory=list)
    ultima_ferramenta_chamada: str | None = None

    def registrar_resultado(self, ferramenta: str, resultado: dict[str, Any]) -> None:
        self.ultima_ferramenta_chamada = ferramenta
        resumo = json.dumps(resultado, ensure_ascii=False)
        if len(resumo) > 600:
            resumo = resumo[:600] + "…(truncado)"
        self.resumo_resultados.append(f"[{ferramenta}] {resumo}")

    def como_contexto(self) -> str:
        if not self.resumo_resultados:
            return ""
        return "Resultados já obtidos nesta pergunta (não repita a mesma chamada sem motivo):\n" + "\n".join(
            self.resumo_resultados
        )


@dataclass
class ResultadoExecucao:
    resposta_final: str | None
    motivo_terminacao: str
    trajetoria: list[dict]
    orcamento: Orcamento


class Agente:
    def __init__(self, cliente: OpenAI, modelo: str, ferramentas: RegistroFerramentas, prompt_sistema: str):
        self.cliente = cliente
        self.modelo = modelo
        self.ferramentas = ferramentas
        self.prompt_sistema = prompt_sistema

    def _montar_mensagens(self, pergunta: str, estado: EstadoAgente) -> list[dict]:
        mensagens = [
            {"role": "system", "content": self.prompt_sistema},
            {"role": "user", "content": pergunta},
        ]
        contexto = estado.como_contexto()
        if contexto:
            mensagens.append({"role": "system", "content": contexto})
        return mensagens

    def executar(self, pergunta: str, orcamento: Orcamento) -> ResultadoExecucao:
        estado = EstadoAgente(pergunta_original=pergunta)
        trajetoria: list[dict] = []

        while True:
            motivo = orcamento.motivo_se_excedido()
            if motivo is not None:
                return ResultadoExecucao(None, motivo, trajetoria, orcamento)

            resposta = self.cliente.chat.completions.create(
                model=self.modelo,
                messages=self._montar_mensagens(pergunta, estado),
                tools=self.ferramentas.schemas_para_modelo(),
            )
            escolha = resposta.choices[0]
            tokens_do_passo = resposta.usage.total_tokens if resposta.usage else 0
            orcamento.registrar_passo(tokens_do_passo)

            chamadas = escolha.message.tool_calls or []

            if not chamadas:
                resposta_final = escolha.message.content or ""
                trajetoria.append(
                    {
                        "passo": orcamento.passos_usados,
                        "tipo": "resposta_final",
                        "conteudo": resposta_final,
                        "tokens": tokens_do_passo,
                    }
                )
                return ResultadoExecucao(resposta_final, "resposta_final", trajetoria, orcamento)

            for chamada in chamadas:
                nome = chamada.function.name
                erro_argumentos = None
                try:
                    argumentos = json.loads(chamada.function.arguments or "{}")
                except json.JSONDecodeError as exc:
                    argumentos = {}
                    erro_argumentos = str(exc)

                if erro_argumentos:
                    resultado = {"erro": f"argumentos inválidos do modelo para '{nome}': {erro_argumentos}"}
                else:
                    resultado = self.ferramentas.chamar(nome, argumentos)

                estado.registrar_resultado(nome, resultado)
                trajetoria.append(
                    {
                        "passo": orcamento.passos_usados,
                        "tipo": "chamada_ferramenta",
                        "ferramenta": nome,
                        "argumentos": argumentos,
                        "resultado": resultado,
                        "tokens": tokens_do_passo,
                    }
                )
