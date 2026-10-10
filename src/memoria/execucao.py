"""Uma execução do agente com memória: lê a memória → executa → grava checkpoint → escreve na
memória pela política de `politica.py`.

Checkpoint × memória (Exercício 8, §1): o checkpoint é o estado ÍNTEGRO de UMA execução, lido
uma vez, para retomar; a memória é um FRAGMENTO selecionado de TODAS as execuções, lido por
relevância, para lembrar. O checkpoint guarda o que a retomada precisa — pergunta, gestor,
contexto de memória usado (o estado da memória daquela execução, para reprodução), trajetória
com argumentos e resultados, e quais efeitos colaterais já foram aplicados (`exportar_analise`
com o arquivo gerado), para uma retomada não exportar duas vezes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from src.core.agent import Agente, ResultadoExecucao
from src.core.budget import Orcamento

from .contexto import ContextoMemoria, montar_contexto_memoria
from .memoria import Gravacao, Memoria
from .politica import extrair_preferencia_farmacia, extrair_recorte


@dataclass
class ExecucaoComMemoria:
    resultado: ResultadoExecucao
    contexto: ContextoMemoria
    gravacoes: list[tuple[str, Gravacao]]
    caminho_checkpoint: Path


def executar_com_memoria(
    agente: Agente,
    memoria: Memoria,
    usuario_id: str,
    pergunta: str,
    orcamento: Orcamento,
    pasta_checkpoints: Path,
    hoje: date | None = None,
    escrever: bool = True,
) -> ExecucaoComMemoria:
    hoje = hoje or date.today()
    contexto = montar_contexto_memoria(memoria, usuario_id, pergunta)
    resultado = agente.executar(pergunta, orcamento, contexto_extra=contexto.texto)

    id_execucao = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    efeitos = [
        {"ferramenta": p["ferramenta"], "resultado": p["resultado"]}
        for p in resultado.trajetoria
        if p.get("tipo") == "chamada_ferramenta" and p.get("ferramenta") == "exportar_analise"
    ]
    pasta_checkpoints.mkdir(parents=True, exist_ok=True)
    caminho = pasta_checkpoints / f"{id_execucao}.json"
    caminho.write_text(json.dumps({
        "id_execucao": id_execucao,
        "usuario_id": usuario_id,
        "pergunta": pergunta,
        "contexto_memoria": contexto.texto,
        "trajetoria": resultado.trajetoria,
        "efeitos_colaterais_aplicados": efeitos,
        "motivo_terminacao": resultado.motivo_terminacao,
        "resposta_final": resultado.resposta_final,
    }, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    gravacoes: list[tuple[str, Gravacao]] = []
    if escrever:
        recorte = extrair_recorte(resultado.trajetoria, resultado.motivo_terminacao)
        if recorte.ferramentas:  # execução que não consultou nada não tem recorte a lembrar
            gravacoes.append(("episodica", memoria.gravar_episodio(usuario_id, hoje.isoformat(), pergunta, recorte)))
        preferencia = extrair_preferencia_farmacia(pergunta)
        if preferencia:
            gravacoes.append(("semantica", memoria.gravar_fato(
                f"usuario:{usuario_id}:farmacia_padrao", preferencia, hoje.isoformat(), f"execucao:{id_execucao}"
            )))
    return ExecucaoComMemoria(resultado, contexto, gravacoes, caminho)
