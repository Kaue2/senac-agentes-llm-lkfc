"""CLI do agente — Parte 2: o grafo LangGraph (src/grafo/).

Uso:
  python -m src.main "sua pergunta" [--usuario G-0042] [--sessao s1]
  python -m src.main --pendentes
  python -m src.main --retomar G-0042:s1 --decisao aprovar|rejeitar|editar [--editar '{"explicacao": "..."}'] [--revisor nome]
  python -m src.main --expirar-pendentes

A saída é o objeto validado do contrato (src/grafo/contrato.py::SaidaAgente), em JSON. Mesmo
usuário + mesma sessão = mesma conversa (o checkpoint fica em dados/checkpoints/grafo.db).
O agente da Parte 1 (laço escrito à mão, src/core/agent.py) continua sendo o usado pelos scripts
de avaliação das Aulas 07 e 11.
"""

from __future__ import annotations

import argparse
import json
import sys

sys.stdout.reconfigure(encoding="utf-8")  # console Windows (cp1252) engasga em texto do modelo com acento

from dotenv import load_dotenv

load_dotenv()

from src.grafo.execucao import (  # noqa: E402  (import após load_dotenv de propósito)
    ResultadoTurno,
    executar_turno,
    expirar_pendentes,
    listar_pendentes,
    montar_dependencias,
    retomar,
)


def _imprimir(r: ResultadoTurno) -> None:
    print(json.dumps(r.saida.model_dump(), ensure_ascii=False, indent=2))
    if r.interrupcao:
        print("\n--- O grafo parou e espera uma pessoa ---")
        print(json.dumps({k: r.interrupcao[k] for k in ("acao", "argumentos", "consequencia", "prazo_expira_em", "respostas_aceitas")},
                         ensure_ascii=False, indent=2))
        print(f'\nPara responder: python -m src.main --retomar {r.thread_id} --decisao aprovar|rejeitar|editar '
              "[--editar '{\"explicacao\": \"...\"}']")
    if r.caminho_log:
        print(f"[log: {r.caminho_log}]")


def main() -> None:
    p = argparse.ArgumentParser(description="Agente de BI de farmácia (grafo LangGraph).")
    p.add_argument("texto", nargs="*", help="A pergunta, em texto livre.")
    p.add_argument("--usuario", default="G-0000", help="Matrícula pseudônima do gestor.")
    p.add_argument("--sessao", default="s1", help="Identificador da conversa.")
    p.add_argument("--pendentes", action="store_true", help="Lista as aprovações pendentes.")
    p.add_argument("--retomar", metavar="THREAD_ID", help="Responde a uma aprovação pendente.")
    p.add_argument("--decisao", choices=["aprovar", "rejeitar", "editar"])
    p.add_argument("--editar", default=None, help="JSON com os argumentos corrigidos (com --decisao editar).")
    p.add_argument("--revisor", default="cli")
    p.add_argument("--comentario", default="")
    p.add_argument("--expirar-pendentes", action="store_true", help="Expira as aprovações com prazo vencido.")
    args = p.parse_args()

    if args.pendentes:
        from src.grafo.grafo import obter_grafo

        print(json.dumps(listar_pendentes(obter_grafo()), ensure_ascii=False, indent=2))
        return

    try:
        deps, banco = montar_dependencias()
    except RuntimeError as exc:
        print(f"Configuração incompleta: {exc}")
        print("Copie .env.example para .env e preencha as variáveis indicadas.")
        raise SystemExit(1)

    try:
        if args.expirar_pendentes:
            for r in expirar_pendentes(deps):
                _imprimir(r)
            return
        if args.retomar:
            if not args.decisao:
                p.error("--retomar exige --decisao")
            decisao = {"decisao": args.decisao, "revisor": args.revisor, "comentario": args.comentario}
            if args.editar:
                decisao["argumentos"] = json.loads(args.editar)
            _imprimir(retomar(args.retomar, decisao, deps))
            return
        if not args.texto:
            p.error('informe a pergunta: python -m src.main "sua pergunta"')
        _imprimir(executar_turno(" ".join(args.texto), deps, args.usuario, args.sessao))
    finally:
        banco.close()


if __name__ == "__main__":
    main()
