"""Execução da suíte: cada (versão, repetição, caso) roda uma vez e fica gravado em disco.

Retomável: uma execução já gravada não é refeita. O tier gratuito tem limite DIÁRIO de tokens, e
a suíte inteira (24 casos × 2 versões × 2 repetições + ruído) pode não caber num dia — parar no
meio e continuar no dia seguinte não pode misturar resultados nem repetir casos.

Erro de infraestrutura (a API caiu depois das retentativas) interrompe a suíte em vez de contar
como falha do caso: um 429 não é o agente errando, e contá-lo como falha poluiria a comparação.
"""

from __future__ import annotations

import json
import time
from collections import defaultdict
from pathlib import Path

from src.core.agent import Agente
from src.core.budget import Orcamento
from src.projects.farmacia_precos import config, tools_farmacia

from . import avaliadores
from .dataset import Caso

PASTA_EXECUCOES = Path(__file__).resolve().parents[2] / "logs" / "aula11" / "execucoes"


def caminho_execucao(versao: str, repeticao: int, caso_id: str) -> Path:
    return PASTA_EXECUCOES / versao / f"rep{repeticao}" / f"{caso_id}.json"


def executar_caso(agente: Agente, caso: Caso, versao: str, repeticao: int) -> dict:
    destino = caminho_execucao(versao, repeticao, caso.id)
    if destino.exists():
        return json.loads(destino.read_text(encoding="utf-8"))

    # Cada execução exporta para uma pasta própria: a avaliação de RESULTADO conta os arquivos
    # que ESTA execução criou, sem confundir com exportações de outras.
    pasta_exports = destino.parent / "exports" / caso.id
    pasta_exports.mkdir(parents=True, exist_ok=True)
    tools_farmacia.PASTA_EXPORTS = pasta_exports
    antes = set(pasta_exports.iterdir())

    orcamento = Orcamento(max_passos=config.max_passos(), max_tokens=config.max_tokens())
    inicio = time.perf_counter()
    resultado = agente.executar(caso.entrada, orcamento)
    latencia = time.perf_counter() - inicio
    criados = len(set(pasta_exports.iterdir()) - antes)

    resposta = resultado.resposta_final or ""
    props = {
        **avaliadores.deterministico(resposta, caso.esperado),
        **avaliadores.trajetoria(resultado.trajetoria, caso.esperado),
        **avaliadores.resultado(criados, caso.esperado, resultado.motivo_terminacao),
    }
    registro = {
        "caso_id": caso.id,
        "classe": caso.classe,
        "versao": versao,
        "repeticao": repeticao,
        "entrada": caso.entrada,
        "resposta": resposta,
        "motivo_terminacao": resultado.motivo_terminacao,
        "trajetoria": resultado.trajetoria,
        "exportacoes_criadas": criados,
        "propriedades": props,
        "medidas_trajetoria": avaliadores.medidas_de_trajetoria(resultado.trajetoria, caso.esperado),
        "passou": avaliadores.passou(props),
        "tokens": resultado.orcamento.tokens_usados,
        "latencia_s": round(latencia, 3),
    }
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(registro, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return registro


def taxa(registros: list[dict]) -> float:
    return sum(r["passou"] for r in registros) / len(registros) if registros else 0.0


def taxas_por_classe(registros: list[dict]) -> dict[str, float]:
    grupos: dict[str, list[dict]] = defaultdict(list)
    for r in registros:
        grupos[r["classe"]].append(r)
    return {c: taxa(rs) for c, rs in sorted(grupos.items())}


def pass_k(registros: list[dict]) -> dict[str, bool]:
    """Por caso: passou em TODAS as repetições (pass^k)."""
    por_caso: dict[str, list[bool]] = defaultdict(list)
    for r in registros:
        por_caso[r["caso_id"]].append(r["passou"])
    return {c: all(v) for c, v in por_caso.items()}


def propriedade_pass_k(registros: list[dict], propriedade: str) -> bool:
    valores = [r["propriedades"].get(propriedade) for r in registros]
    return all(v for v in valores if v is not None)
