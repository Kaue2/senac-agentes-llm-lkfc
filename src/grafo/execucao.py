"""Executar um turno, retomar uma pausa, expirar pausas vencidas e remover um titular — a camada
entre o grafo e quem o usa (src/main.py, scripts/run_casos_parte2.py, testes).

Cada execução grava um log em `logs/execucoes/` (ou na pasta pedida) que começa pelo CARIMBO — a
combinação em uso (§2.2): commit, modelo, versões dos prompts, k e limiar do RAG, versão do
LangGraph, `recursion_limit`, tetos. É essa amarra que distingue exemplo real de exemplo plausível.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from typing import Any

from langgraph.errors import GraphRecursionError
from langgraph.types import Command

from .contrato import Entrada, SaidaAgente
from .dependencias import Dependencias, Tetos, carregar_prompts
from .grafo import PASTA_RAIZ, RECURSION_LIMIT, config_da_thread, obter_grafo

PASTA_LOGS_EXECUCOES = PASTA_RAIZ / "logs" / "execucoes"


def commit_atual() -> str:
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=PASTA_RAIZ, capture_output=True, text=True, check=True).stdout.strip()
        sujo = subprocess.run(["git", "status", "--porcelain", "--", "src"], cwd=PASTA_RAIZ, capture_output=True, text=True).stdout.strip()
        return sha + ("+alteracoes-locais-em-src" if sujo else "")
    except (OSError, subprocess.CalledProcessError):
        return "desconhecido"


def carimbo(deps: Dependencias) -> dict[str, str]:
    from src.rag.resposta import K_PADRAO, LIMIAR_PADRAO

    return {
        "commit": commit_atual(),
        "data_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **deps.carimbo(),
        "rag": f"indice=dados/indices/estrutura.db k={K_PADRAO} limiar={LIMIAR_PADRAO} somente_vigentes",
        "langgraph": version("langgraph"),
        "recursion_limit": str(RECURSION_LIMIT),
        "checkpointer": "SqliteSaver(dados/checkpoints/grafo.db)",
    }


@dataclass
class ResultadoTurno:
    thread_id: str
    saida: SaidaAgente
    interrupcao: dict[str, Any] | None
    estado: dict[str, Any]
    caminho_log: Path | None
    carimbo: dict[str, str]


def montar_dependencias(memoria: bool | None = None, pasta_memoria: Path | None = None) -> tuple[Dependencias, Any]:
    """Dependências do sistema de verdade: modelo ativo do .env, banco de preços (real ou espelho),
    as 5 ferramentas (4 da Parte 1 + RAG) e a memória de longo prazo. Devolve também o banco, para
    o chamador fechar."""
    from src.core.llm_client import ConfiguracaoModelo, criar_cliente
    from src.core.tools import RegistroFerramentas
    from src.projects.farmacia_precos.db import BancoPrecos
    from src.projects.farmacia_precos.tools_conhecimento import registrar_ferramenta_conhecimento
    from src.projects.farmacia_precos.tools_farmacia import registrar_ferramentas_farmacia
    from src.rag.embeddings import modelo_do_ambiente
    from src.rag.indice import PASTA_INDICES, IndiceVetorial

    config = ConfiguracaoModelo.do_ambiente()
    banco = BancoPrecos()
    embeddings = modelo_do_ambiente()
    registro = RegistroFerramentas()
    registrar_ferramentas_farmacia(registro, banco)
    registrar_ferramenta_conhecimento(registro, IndiceVetorial.carregar(PASTA_INDICES / "estrutura.db"), embeddings)

    if memoria is None:
        memoria = os.environ.get("AGENT_MEMORIA", "1") != "0"
    mem = None
    if memoria:
        from src.memoria.memoria import PASTA_MEMORIA_PADRAO, Memoria

        mem = Memoria(embeddings, pasta_memoria or PASTA_MEMORIA_PADRAO)
    prompt_agente, prompt_triagem = carregar_prompts()
    deps = Dependencias(
        cliente=criar_cliente(config), modelo=config.modelo, ferramentas=registro,
        prompt_agente=prompt_agente, prompt_triagem=prompt_triagem,
        fonte_dados=banco.fonte, memoria=mem, tetos=Tetos.do_ambiente(),
    )
    return deps, banco


def _interrupcao_pendente(grafo, config: dict) -> dict | None:
    snapshot = grafo.get_state(config)
    for tarefa in snapshot.tasks:
        for itr in tarefa.interrupts:
            return itr.value
    return None


def _saida_de(estado: dict, interrupcao: dict | None, thread_id: str) -> SaidaAgente:
    if interrupcao is not None:
        return SaidaAgente(
            resultado=(
                f"Aguardando aprovação para {interrupcao['acao']}: {interrupcao['consequencia']} "
                f"Prazo: {interrupcao['prazo_expira_em']}."
            ),
            suficiencia="aguardando_aprovacao",
            motivo_insuficiencia="ação de escrita aguardando revisor humano",
            suposicoes=(estado.get("triagem") or {}).get("suposicoes", []),
            motivo_terminacao="pausado_aguardando_humano",
            thread_id=thread_id,
            turno=estado.get("turno", 1),
        )
    return SaidaAgente.model_validate(estado["saida"])


def _invocar(grafo, entrada_ou_comando, config: dict, deps: Dependencias) -> dict:
    try:
        return grafo.invoke(entrada_ou_comando, config, context=deps)
    except GraphRecursionError:
        # A rede de segurança do framework disparou antes dos nossos tetos: é defeito do grafo, e o
        # motivo de término precisa dizer isso, e não "orçamento".
        estado = dict(grafo.get_state(config).values)
        estado["saida"] = SaidaAgente(
            resultado="A execução foi interrompida pelo limite de recursão do grafo.", suficiencia="insuficiente",
            motivo_insuficiencia="limite_recursao_framework", motivo_terminacao="limite_recursao_framework",
            thread_id=config["configurable"]["thread_id"], turno=estado.get("turno", 1),
        ).model_dump()
        return estado


def _medicoes(estado: dict) -> dict[str, Any]:
    eventos = {e["no"]: e for e in estado.get("eventos", [])}
    medicoes: dict[str, Any] = {
        "chamadas_recuperacao_rag": sum(1 for p in estado.get("trajetoria", [])
                                        if p.get("tipo") == "chamada_ferramenta" and p.get("ferramenta") == "consultar_base_conhecimento"),
        "chamadas_modelo_laco": estado.get("passos", 0),
        "tokens_turno": estado.get("tokens", 0),
    }
    if "carregar_memoria" in eventos and "triagem" in eventos:
        m, t = eventos["carregar_memoria"], eventos["triagem"]
        medicoes["paralelo"] = {
            "memoria_ms": m["ms"], "triagem_ms": t["ms"], "soma_ms": round(m["ms"] + t["ms"], 1),
            "maior_ms": max(m["ms"], t["ms"]),
            "decorrido_ms": round(1000 * (max(m["fim"], t["fim"]) - min(m["inicio"], t["inicio"])), 1),
        }
    return medicoes


def gravar_log(pasta: Path, nome: str, registro: dict) -> Path:
    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / nome
    caminho.write_text(json.dumps(registro, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return caminho


def _finalizar(grafo, estado: dict, config: dict, deps: Dependencias, tipo: str, pedido: Any,
               pasta_logs: Path | None, nome_log: str | None) -> ResultadoTurno:
    thread_id = config["configurable"]["thread_id"]
    interrupcao = _interrupcao_pendente(grafo, {"configurable": {"thread_id": thread_id}})
    saida = _saida_de(estado, interrupcao, thread_id)
    marca = carimbo(deps)
    caminho = None
    if pasta_logs is not False:
        pasta = pasta_logs or PASTA_LOGS_EXECUCOES
        nome = nome_log or f"{thread_id.replace(':', '_')}_t{estado.get('turno', 0)}_{tipo}_{datetime.now().strftime('%Y%m%dT%H%M%S')}.json"
        caminho = gravar_log(pasta, nome, {
            "carimbo": marca,
            "tipo": tipo,
            "thread_id": thread_id,
            "checkpoint_id": grafo.get_state({"configurable": {"thread_id": thread_id}}).config["configurable"].get("checkpoint_id"),
            "pedido": pedido,
            "saida": saida.model_dump(),
            "interrupcao": interrupcao,
            "medicoes": _medicoes(estado),
            "triagem": estado.get("triagem"),
            "memoria_usada": estado.get("memoria_usada"),
            "gravacoes_memoria": estado.get("gravacoes_memoria"),
            "decisao_humana": estado.get("decisao_humana"),
            "trajetoria": estado.get("trajetoria", []),
            "eventos": estado.get("eventos", []),
        })
    return ResultadoTurno(thread_id, saida, interrupcao, estado, caminho, marca)


def executar_turno(texto: str, deps: Dependencias, usuario_id: str = "G-0000", sessao_id: str = "s1",
                   grafo=None, pasta_logs: Path | None = None, nome_log: str | None = None) -> ResultadoTurno:
    grafo = grafo or obter_grafo()
    entrada = Entrada(texto=texto, usuario_id=usuario_id, sessao_id=sessao_id)
    config = config_da_thread(entrada.thread_id)
    pendente = _interrupcao_pendente(grafo, config)
    if pendente is not None:
        # Uma mensagem nova numa conversa com aprovação pendente descartaria a pausa sem resposta
        # (o LangGraph recomeçaria a partir da entrada). Política: recusar até a pausa ser resolvida.
        estado = dict(grafo.get_state(config).values)
        return ResultadoTurno(entrada.thread_id, _saida_de(estado, pendente, entrada.thread_id), pendente, estado, None, carimbo(deps))
    estado = _invocar(grafo, {"entrada": entrada.model_dump()}, config, deps)
    return _finalizar(grafo, estado, config, deps, "turno", entrada.model_dump(), pasta_logs, nome_log)


def retomar(thread_id: str, decisao: dict, deps: Dependencias, grafo=None, checkpoint_id: str | None = None,
            pasta_logs: Path | None = None, nome_log: str | None = None) -> ResultadoTurno:
    """Entrega a decisão humana à pausa. `checkpoint_id` reentrega a decisão a partir de um
    checkpoint específico — é assim que a demonstração do §8.5 simula a mesma aprovação chegando
    duas vezes (o caminho de uma retentativa depois de queda de processo)."""
    grafo = grafo or obter_grafo()
    config = config_da_thread(thread_id, checkpoint_id)
    estado = _invocar(grafo, Command(resume=decisao), config, deps)
    return _finalizar(grafo, estado, config, deps, "retomada", decisao, pasta_logs, nome_log)


def listar_pendentes(grafo=None) -> list[dict]:
    grafo = grafo or obter_grafo()
    threads = sorted({c.config["configurable"]["thread_id"] for c in grafo.checkpointer.list(None)})
    pendentes = []
    for t in threads:
        itr = _interrupcao_pendente(grafo, {"configurable": {"thread_id": t}})
        if itr is not None:
            pendentes.append({"thread_id": t, **itr})
    return pendentes


def expirar_pendentes(deps: Dependencias, grafo=None, pasta_logs: Path | None = None) -> list[ResultadoTurno]:
    """Rotina (cron) do §8.4: toda pausa com prazo vencido é retomada com `expirou`. Sem ela, uma
    pausa esquecida ficaria no checkpoint para sempre — o estado sem saída do §3.2."""
    agora = deps.agora()
    resultados = []
    for p in listar_pendentes(grafo):
        if agora > datetime.fromisoformat(p["prazo_expira_em"]):
            resultados.append(retomar(p["thread_id"], {"decisao": "expirou", "revisor": "rotina-de-expiracao"}, deps, grafo, pasta_logs=pasta_logs))
    return resultados


def remover_titular(usuario_id: str, deps: Dependencias, grafo=None, pastas_logs: list[Path] | None = None) -> dict[str, Any]:
    """Remoção a pedido do titular com a cobertura do §5.4: memória (episódica, semântica,
    procedural, cache de embeddings, registro de descartes), CHECKPOINTS do grafo (guardam a entrada
    e os argumentos de cada passo) e LOGS. Verificação independente com `Memoria.varrer`."""
    grafo = grafo or obter_grafo()
    pastas_logs = pastas_logs or [PASTA_RAIZ / "logs"]
    relatorio: dict[str, Any] = {}
    if deps.memoria is not None:
        relatorio["memoria"] = deps.memoria.remover_titular(usuario_id, pastas_logs)
    threads = sorted({c.config["configurable"]["thread_id"] for c in grafo.checkpointer.list(None)
                      if c.config["configurable"]["thread_id"].startswith(f"{usuario_id}:")})
    for t in threads:
        grafo.checkpointer.delete_thread(t)
    conn = grafo.checkpointer.conn
    conn.execute("VACUUM")
    # O SqliteSaver usa WAL: as páginas apagadas continuam no arquivo `grafo.db-wal` até um
    # checkpoint do WAL. Sem isto, a varredura por bytes encontra a matrícula (achado do teste
    # test_remocao_por_titular_alcanca_memoria_checkpoint_e_log).
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    relatorio["threads_de_checkpoint_apagadas"] = threads
    return relatorio
