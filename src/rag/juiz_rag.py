"""Juiz LLM de fidelidade e correção do RAG (Exercício 7, §4).

O modelo do juiz vem de `JUDGE_MODEL` (mesmo provedor do modelo ativo). Se não estiver
preenchido, usa o próprio modelo ativo — e o carimbo registra isso, porque juiz igual ao gerador
é a condição em que o viés de auto-preferência mais pesa.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

from openai import OpenAI

from src.core.prompts import carregar_prompt

from .resposta import RespostaRAG, montar_contexto


@dataclass(frozen=True)
class Veredito:
    fiel: bool | None
    correta: bool | None
    justificativa: str
    erro: str | None = None


class JuizRAG:
    def __init__(self, cliente: OpenAI, modelo_padrao: str) -> None:
        self.cliente = cliente
        self.modelo = os.environ.get("JUDGE_MODEL", "").strip() or modelo_padrao
        self.prompt = carregar_prompt("juiz_fidelidade_rag_v1")

    def carimbo(self) -> dict[str, str]:
        return {"modelo_juiz": self.modelo, "rubrica_juiz": self.prompt.rotulo}

    def julgar(self, r: RespostaRAG, referencia: str | None) -> Veredito:
        mensagem = self.prompt.preencher(
            pergunta=r.pergunta,
            trechos=montar_contexto(r.recuperados) if r.recuperados else "(nenhum)",
            referencia=referencia or "(a base de conhecimento não tem resposta; o correto é recusar)",
            resposta=r.resposta or "(vazia)",
        )
        resposta = self.cliente.chat.completions.create(
            model=self.modelo,
            messages=[{"role": "user", "content": mensagem}],
            temperature=0.0,
            # 600: a saída é um JSON de uma frase; e o juiz (qwen3.8-27b) tem teto de 1.000 tokens
            # de SAÍDA por minuto no tier gratuito — pedir mais que isso é recusado na hora.
            max_tokens=600,
            response_format={"type": "json_object"},
        )
        conteudo = resposta.choices[0].message.content or ""
        try:
            dados = json.loads(conteudo)
            return Veredito(bool(dados["fiel"]), bool(dados["correta"]), str(dados.get("justificativa", "")))
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            return Veredito(None, None, "", erro=f"saída do juiz fora do contrato: {exc}: {conteudo[:200]}")
