"""Log da trajetória do agente (docs/01-primeira-entrega.md, item 4.1: "log da trajetória").

Genérico: qualquer projeto grava no mesmo formato, só muda a pasta de destino.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .agent import ResultadoExecucao


def salvar_trajetoria(
    pasta_logs: Path,
    nome_arquivo: str,
    pergunta: str,
    modelo: str,
    resultado: ResultadoExecucao,
    metadados_extra: dict[str, Any] | None = None,
) -> Path:
    pasta_logs.mkdir(parents=True, exist_ok=True)
    caminho = pasta_logs / nome_arquivo

    registro = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "modelo": modelo,
        "pergunta": pergunta,
        "motivo_terminacao": resultado.motivo_terminacao,
        "resposta_final": resultado.resposta_final,
        "orcamento": {
            "passos_usados": resultado.orcamento.passos_usados,
            "max_passos": resultado.orcamento.max_passos,
            "tokens_usados": resultado.orcamento.tokens_usados,
            "max_tokens": resultado.orcamento.max_tokens,
        },
        "trajetoria": resultado.trajetoria,
    }
    if metadados_extra:
        registro["metadados"] = metadados_extra

    caminho.write_text(json.dumps(registro, ensure_ascii=False, indent=2), encoding="utf-8")
    return caminho
