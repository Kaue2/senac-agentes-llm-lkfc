"""Juiz LLM da propriedade "fundamentada na trajetória" (Exercício 11, §3), e a validação dele
contra rótulos humanos.

O juiz só passa a contar para a regra de promoção depois de ADOTADO: concordância com os rótulos
humanos >= `LIMIAR_ADOCAO`, declarado aqui antes de qualquer medição (2026-10-09).
"""

from __future__ import annotations

import csv
import json
import os
from dataclasses import dataclass
from pathlib import Path

from openai import OpenAI

from src.core.prompts import carregar_prompt

from .avaliadores import chamadas

# 0,85: abaixo disso, em 30 rótulos, o juiz erra mais de 4 — e o erro que mais custa (dizer
# "fundamentada" para um preço inventado) já pode ser metade dos desacordos. Decidido antes de medir.
LIMIAR_ADOCAO = 0.85
MINIMO_ROTULOS = 30
CAMINHO_ROTULOS = Path(__file__).resolve().parents[2] / "dados" / "avaliacao" / "rotulos_juiz_v1.csv"
COLUNAS_ROTULOS = (
    "amostra_id", "caso_id", "versao", "repeticao", "pergunta", "resultados_ferramentas", "resposta",
    "rotulo_humano", "nota_humana", "rotulador", "veredito_juiz", "justificativa_juiz", "classificacao_desacordo",
)
_MAX_CARACTERES_RESULTADOS = 3000


@dataclass(frozen=True)
class VereditoJuiz:
    fundamentada: bool | None
    justificativa: str
    erro: str | None = None


def resultados_para_juiz(trajetoria: list[dict]) -> str:
    """O que as ferramentas devolveram, truncado no mesmo limite para todo caso (o juiz não pode
    ver mais de um caso do que de outro)."""
    partes = [
        f"[{c['ferramenta']}] argumentos={json.dumps(c.get('argumentos', {}), ensure_ascii=False)} "
        f"resultado={json.dumps(c.get('resultado', {}), ensure_ascii=False, default=str)}"
        for c in chamadas(trajetoria)
    ]
    texto = "\n".join(partes) or "(nenhuma ferramenta foi chamada)"
    return texto[:_MAX_CARACTERES_RESULTADOS]


class JuizFundamentacao:
    def __init__(self, cliente: OpenAI, modelo_padrao: str) -> None:
        self.cliente = cliente
        self.modelo = os.environ.get("JUDGE_MODEL", "").strip() or modelo_padrao
        self.prompt = carregar_prompt("juiz_fundamentacao_v1")

    def julgar(self, pergunta: str, resultados: str, resposta: str) -> VereditoJuiz:
        mensagem = self.prompt.preencher(pergunta=pergunta, resultados=resultados, resposta=resposta or "(vazia)")
        saida = self.cliente.chat.completions.create(
            model=self.modelo,
            messages=[{"role": "user", "content": mensagem}],
            temperature=0.0,
            # 600: a saída é um JSON de uma frase; e o juiz (qwen3.8-27b) tem teto de 1.000 tokens
            # de SAÍDA por minuto no tier gratuito — pedir mais que isso é recusado na hora.
            max_tokens=600,
            response_format={"type": "json_object"},
        )
        conteudo = saida.choices[0].message.content or ""
        try:
            dados = json.loads(conteudo)
            return VereditoJuiz(bool(dados["fundamentada"]), str(dados.get("justificativa", "")))
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            return VereditoJuiz(None, "", erro=f"saída fora do contrato: {exc}: {conteudo[:200]}")


@dataclass(frozen=True)
class Concordancia:
    n: int
    juiz_sim_humano_sim: int
    juiz_sim_humano_nao: int
    juiz_nao_humano_sim: int
    juiz_nao_humano_nao: int

    @property
    def taxa(self) -> float:
        return (self.juiz_sim_humano_sim + self.juiz_nao_humano_nao) / self.n if self.n else 0.0

    @property
    def adotado(self) -> bool:
        return self.n >= MINIMO_ROTULOS and self.taxa >= LIMIAR_ADOCAO


def ler_rotulos(caminho: Path = CAMINHO_ROTULOS) -> list[dict]:
    if not caminho.exists():
        return []
    with caminho.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def concordancia(linhas: list[dict]) -> Concordancia:
    """Só entram amostras com rótulo HUMANO (sim/nao) e veredito do juiz. Rótulo vazio não é
    'não': é amostra não rotulada."""
    pares = [
        (l["veredito_juiz"], l["rotulo_humano"].strip().lower())
        for l in linhas
        if l.get("rotulo_humano", "").strip().lower() in ("sim", "nao", "não") and l.get("veredito_juiz") in ("sim", "nao")
    ]
    pares = [(j, "nao" if h == "não" else h) for j, h in pares]
    return Concordancia(
        n=len(pares),
        juiz_sim_humano_sim=sum(1 for j, h in pares if j == "sim" and h == "sim"),
        juiz_sim_humano_nao=sum(1 for j, h in pares if j == "sim" and h == "nao"),
        juiz_nao_humano_sim=sum(1 for j, h in pares if j == "nao" and h == "sim"),
        juiz_nao_humano_nao=sum(1 for j, h in pares if j == "nao" and h == "nao"),
    )
