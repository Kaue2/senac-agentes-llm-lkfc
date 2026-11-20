"""Roda o golden dataset no SISTEMA ENTREGUE (Parte 3, §1.4): o mesmo grafo e o mesmo ponto de
entrada do README (`src.grafo.execucao.executar_turno` / `retomar`), com o modelo ativo do .env.

Uso:
  python -m evals.rodar --versao 2.0.0                 # rodada nova
  python -m evals.rodar --versao 2.0.0 --continuar evals/resultados/v2.0.0_20261120T1500
  python -m evals.rodar --versao 2.0.0 --casos G01 S03 # só alguns casos (rodada parcial)

Grava em `evals/resultados/v<versao>_<data>/`: um JSON por caso em `casos/`, o `traces.jsonl`
da rodada (os traces OpenTelemetry de todas as execuções) e o `resumo.json`.

Condições fixas da rodada (vão para o carimbo):
- banco: SEMPRE o espelho sintético — a connection string do banco real é apagada do ambiente
  antes de montar as dependências, e `exigir_espelho` confere. O golden foi calculado do espelho,
  e o resultado é commitado: dado real do cliente não pode entrar aqui (docs/case.md §9);
- data de referência das regras de domínio: 2026-09-20 (o dia seguinte à última coleta do
  espelho), salvo `data_referencia` no caso;
- memória: vazia no início da rodada, em pasta própria, e um gestor (`G-<caso>`) por caso;
- exportações: uma pasta por caso, para o nível de resultado contar só o que ESTE caso criou.

Retomável: caso já gravado não roda de novo. Erro do provedor depois das retentativas da biblioteca
interrompe a rodada sem gravar o caso — um 429 não é o agente errando.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
DATA_REFERENCIA_PADRAO = "2026-09-20"


def _preparar_ambiente(pasta_rodada: Path) -> None:
    os.environ["FRACTALPRECOS_CONNECTION_STRING"] = ""  # antes do load_dotenv: o .env não sobrescreve
    os.environ["OTEL_ARQUIVO_TRACES"] = str(pasta_rodada / "traces.jsonl")
    os.environ.pop("OTEL_DESLIGADO", None)


class Gravador:
    """Envolve o cliente do modelo e guarda o que foi ENVIADO, por caso: é com isso que a suíte
    confere se um dado pessoal saiu para o provedor (nível de resultado, §3.4)."""

    def __init__(self, cliente) -> None:
        self._cliente = cliente
        self.enviado: list = []
        gravador = self

        class _Comp:
            def create(self, **kw):
                gravador.enviado.append(kw.get("messages", []))
                return cliente.chat.completions.create(**kw)

        self.chat = type("Chat", (), {"completions": _Comp()})()


def _contar_exports(pasta: Path) -> int:
    return len(list(pasta.glob("*.md"))) if pasta.exists() else 0


def _traces_da_thread(arquivo: Path, thread_prefixo: str) -> str:
    if not arquivo.exists():
        return ""
    spans = [json.loads(l) for l in arquivo.read_text(encoding="utf-8").splitlines() if l.strip()]
    ids = {s["context"]["trace_id"] for s in spans
           if not s.get("parent_id") and str(s["attributes"].get("app.thread_id", "")).startswith(thread_prefixo)}
    return "\n".join(json.dumps(s, ensure_ascii=False) for s in spans if s["context"]["trace_id"] in ids)


def rodar_caso(caso, deps, grafo, pasta_rodada: Path, rotulo_rodada: str, gravador: Gravador) -> dict:
    from src.grafo.execucao import executar_turno, retomar
    from src.projects.farmacia_precos.tools_farmacia import _exportar_analise

    from . import avaliar

    esp = caso.esperado
    os.environ["AGENT_DATA_REFERENCIA"] = esp.get("data_referencia", DATA_REFERENCIA_PADRAO)
    pasta_exports = RAIZ / "dados" / "exports_evals" / rotulo_rodada / caso.id
    original = deps.ferramentas._ferramentas["exportar_analise"]
    deps.ferramentas._ferramentas["exportar_analise"] = dataclasses.replace(
        original, handler=lambda pergunta, dados_resumo, explicacao: _exportar_analise(pergunta, dados_resumo, explicacao, pasta_exports))
    gravador.enviado = []
    usuario = f"G-{caso.id}"
    decisoes = list(esp.get("aprovacoes", []))
    invocacoes, saidas, trajetoria, pausas, ja_existia = [], [], [], [], []
    estado_final: dict = {}
    thread = ""

    def registrar(r, tipo: str, t0: float) -> None:
        invocacoes.append({"tipo": tipo, "thread_id": r.thread_id, "ms": round(1000 * (time.time() - t0)),
                           "tokens": r.estado.get("tokens", 0), "motivo_terminacao": r.saida.motivo_terminacao,
                           "suficiencia": r.saida.suficiencia})
        if r.saida.motivo_terminacao.startswith("erro_fatal_modelo"):
            raise RuntimeError(f"erro de infraestrutura em {caso.id}: {r.saida.motivo_terminacao}")

    for turno in caso.turnos_ou_entrada:
        t0 = time.time()
        r = executar_turno(turno["texto"], deps, usuario, f"{turno['sessao']}-{rotulo_rodada}", grafo=grafo, pasta_logs=False)
        registrar(r, "turno", t0)
        thread = r.thread_id
        ultima_decisao, cp_pausa = None, None
        while r.interrupcao is not None:
            pausas.append(r.interrupcao)
            if not decisoes:
                break  # pausa sem decisão no roteiro: fica pendente, e nada é exportado
            cp_pausa = grafo.get_state({"configurable": {"thread_id": thread}}).config["configurable"]["checkpoint_id"]
            ultima_decisao = decisoes.pop(0)
            t0 = time.time()
            r = retomar(thread, ultima_decisao, deps, grafo, pasta_logs=False)
            registrar(r, "retomada", t0)
            ja_existia += [a.ja_existia for a in r.saida.acoes_executadas]
        if esp.get("repetir_aprovacao") and ultima_decisao and cp_pausa:
            t0 = time.time()
            r = retomar(thread, ultima_decisao, deps, grafo, checkpoint_id=cp_pausa, pasta_logs=False)
            registrar(r, "retomada_repetida", t0)
            ja_existia += [a.ja_existia for a in r.saida.acoes_executadas]
        saidas.append(r.saida.model_dump())
        trajetoria += r.estado.get("trajetoria", [])
        estado_final = r.estado

    deps.ferramentas._ferramentas["exportar_analise"] = original
    persistido = {
        "trace": _traces_da_thread(pasta_rodada / "traces.jsonl", f"{usuario}:"),
        "checkpoint": json.dumps(dict(grafo.get_state({"configurable": {"thread_id": thread}}).values), ensure_ascii=False, default=str),
        "memoria": (deps.memoria.caminho_db.read_bytes().decode("utf-8", errors="ignore") if deps.memoria else ""),
    }
    niveis = avaliar.avaliar(caso, saidas, trajetoria, _contar_exports(pasta_exports), pausas, ja_existia,
                             json.dumps(gravador.enviado, ensure_ascii=False), persistido, estado_final.get("contexto_memoria", ""))
    return {
        "id": caso.id, "classe": caso.classe, "origem": caso.origem, "entrada": caso.entrada,
        "passou": avaliar.passou(niveis), "falhas": avaliar.falhas(niveis), "niveis": niveis,
        "saidas": saidas, "pausas": pausas, "ja_existia": ja_existia, "exportacoes": _contar_exports(pasta_exports),
        "invocacoes": invocacoes, "trajetoria": trajetoria,
    }


def resumir(pasta: Path, carimbo: dict) -> dict:
    casos = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((pasta / "casos").glob("*.json"))]
    por_classe: dict[str, list[bool]] = defaultdict(list)
    for c in casos:
        por_classe[c["classe"]].append(c["passou"])
    return {
        "carimbo": carimbo,
        "n_casos": len(casos),
        "taxa": sum(c["passou"] for c in casos) / len(casos) if casos else 0.0,
        "por_classe": {k: {"n": len(v), "passou": sum(v), "taxa": sum(v) / len(v)} for k, v in sorted(por_classe.items())},
        "falhas": {c["id"]: c["falhas"] for c in casos if not c["passou"]},
    }


def main() -> None:
    p = argparse.ArgumentParser(description="Roda o golden dataset no sistema entregue.")
    p.add_argument("--versao", required=True, help="Versão do sistema sob teste; precisa bater com src/versao.py.")
    p.add_argument("--continuar", type=Path, help="Pasta de uma rodada interrompida.")
    p.add_argument("--casos", nargs="*", help="Só estes ids.")
    p.add_argument("--pausa", type=float, default=4.0, help="Segundos entre casos (limite por minuto do tier gratuito).")
    args = p.parse_args()

    rotulo = args.continuar.name.split("_", 1)[1] if args.continuar else datetime.now().strftime("%Y%m%dT%H%M")
    pasta = args.continuar or RAIZ / "evals" / "resultados" / f"v{args.versao}_{rotulo}"
    (pasta / "casos").mkdir(parents=True, exist_ok=True)
    _preparar_ambiente(pasta)
    sys.stdout.reconfigure(encoding="utf-8")

    from dotenv import load_dotenv

    load_dotenv(RAIZ / ".env")
    from importlib.metadata import version

    from src.grafo.execucao import carimbo as carimbo_execucao
    from src.grafo.execucao import montar_dependencias
    from src.grafo.grafo import obter_grafo
    from src.projects.farmacia_precos.fabrica import exigir_espelho
    from src.versao import SISTEMA_VERSAO

    from . import dataset

    if args.versao != SISTEMA_VERSAO:
        raise SystemExit(f"--versao {args.versao} difere de src/versao.py ({SISTEMA_VERSAO}): a rodada seria rotulada errado.")
    deps, banco = montar_dependencias(memoria=True, pasta_memoria=RAIZ / "dados" / "memoria_evals" / rotulo)
    exigir_espelho(banco)
    gravador = Gravador(deps.cliente)
    deps.cliente = gravador
    grafo = obter_grafo(RAIZ / "dados" / "checkpoints" / f"evals-{rotulo}.db")
    casos = dataset.carregar()
    carimbo = {
        **carimbo_execucao(deps),
        "dataset": f"golden_v2 v{dataset.VERSAO} sha256:{dataset.hash_arquivo()}",
        "dataset_resumo": dataset.resumo(casos),
        "data_referencia_padrao": DATA_REFERENCIA_PADRAO,
        "juiz": "não adotado (ver docs/evals.md §3)",
        "opentelemetry": version("opentelemetry-sdk"),
    }
    (pasta / "carimbo.json").write_text(json.dumps(carimbo, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        for caso in casos:
            if args.casos and caso.id not in args.casos:
                continue
            destino = pasta / "casos" / f"{caso.id}.json"
            if destino.exists():
                continue
            print(f"{caso.id:4} {caso.classe:16}", end=" ", flush=True)
            registro = rodar_caso(caso, deps, grafo, pasta, rotulo, gravador)
            destino.write_text(json.dumps(registro, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            print("ok " if registro["passou"] else "FALHOU", ", ".join(registro["falhas"]))
            time.sleep(args.pausa)
    finally:
        banco.close()
        resumo = resumir(pasta, carimbo)
        (pasta / "resumo.json").write_text(json.dumps(resumo, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n{resumo['n_casos']} casos, taxa {100 * resumo['taxa']:.1f}% -> {pasta.relative_to(RAIZ)}")


if __name__ == "__main__":
    main()
