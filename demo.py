"""Demonstração do agente de BI de farmácia, com um comando só.

Uso:
  python demo.py                      # roda as 5 cenas da apresentação, em sequência
  python demo.py --cena 5             # roda só uma cena (1 a 5)
  python demo.py --pergunta "texto"   # faz uma pergunta livre ao agente
  python demo.py --json               # mostra também o objeto de saída completo (SaidaAgente)
  python demo.py --sintetico          # usa o espelho sintético mesmo com o banco real configurado

As cenas:
  1. caminho feliz         — preço de um produto numa farmácia, com a fonte
  2. regra da rede (RAG)   — busca no corpus e cita o trecho
  3. pergunta incompleta   — o sistema pergunta o que falta e, com a resposta, atende
  4. segurança             — pergunta com CPF e remédio controlado é recusada
  5. governança            — pedido de exportar: o grafo para, espera aprovação e não duplica

Na cena 5, num terminal interativo, quem decide a aprovação é você (aprovar, rejeitar ou editar);
fora de um terminal interativo (ou com --auto), a aprovação é automática.

Fonte dos dados: o banco real do fractal-precos, se FRACTALPRECOS_CONNECTION_STRING estiver no .env
e a conexão abrir; senão, o espelho com dados sintéticos (a troca é automática, src/projects/
farmacia_precos/db.py). Com --sintetico, o espelho é usado sempre. O que a demonstração grava (logs
em logs/execucoes/, memória em dados/memoria_demo/, exportações em dados/exports/) fica fora do git:
a saída com dado real é para exibir, não para versionar (docs/case.md §9).
Se o espelho ou o índice do corpus ainda não existirem, eles são gerados antes da primeira cena.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
import warnings
from datetime import datetime
from pathlib import Path

# Tela limpa para a demonstração: sem barra de download nem avisos do HuggingFace e, com o modelo de
# embedding já baixado, sem consultar o Hub (economiza ~1 min de checagem online na inicialização).
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("HF_HUB_VERBOSITY", "error")
_cache_fastembed = Path(os.environ.get("FASTEMBED_CACHE_PATH", Path(tempfile.gettempdir()) / "fastembed_cache"))
if any(_cache_fastembed.glob("models--*e5-large*")):
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
warnings.filterwarnings("ignore")

sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv

# --sintetico precisa valer antes do load_dotenv: variável já definida no ambiente não é
# sobrescrita pelo .env.
if "--sintetico" in sys.argv:
    os.environ["FRACTALPRECOS_CONNECTION_STRING"] = ""
load_dotenv()

RAIZ = Path(__file__).resolve().parent
PASTA_MEMORIA_DEMO = RAIZ / "dados" / "memoria_demo"
PAUSA_ENTRE_CENAS = 3  # segundos: o tier gratuito do provedor limita tokens por minuto
LARGURA = 92

CENAS = [
    ("Caminho feliz: preço com fonte",
     "O gestor pergunta em texto livre; a resposta traz o número, a view de onde veio e a data da coleta.",
     ["Qual o preço atual da Novalgina 500mg na farmácia Araujo?"]),
    ("Regra da rede, com citação (RAG)",
     "A pergunta é sobre política, não sobre preço: o agente decide buscar no corpus e cita o trecho.",
     ["O desconto do PBM conta para o teto de desconto da rede?"]),
    ("Pergunta incompleta: o sistema pergunta o que falta",
     "Falta o produto. A triagem pergunta uma vez; com a resposta, a mesma conversa é atendida.",
     ["quanto ta o remedio na drogasil?", "a trayenta 5mg"]),
    ("Segurança: dado de paciente é recusado na entrada",
     "CPF e remédio controlado: a triagem recusa antes de qualquer ferramenta, e nada vai para a memória.",
     ["quantas caixas de clonazepam o cliente de cpf 123.456.789-09 comprou esse mes?"]),
    ("Governança: exportar exige aprovação humana",
     "Salvar a análise é a única escrita do sistema: o grafo para, mostra a consequência e espera.",
     ["Qual o preço da Trayenta 5mg na Drogasil? Salva essa análise pra eu mandar pra diretoria."]),
]


# ----------------------------------------------------------------------------- preparação

def preparar_ambiente() -> None:
    """Gera o que a demonstração precisa e ainda não existe: o espelho sintético e o índice."""
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        sys.exit("Falta OPENAI_API_KEY no .env (copie .env.example para .env e preencha a chave do provedor).")
    passos = []
    if not (RAIZ / "dados" / "precos_mock.db").exists():
        passos += [["scripts/gerar_dados_sinteticos.py"], ["scripts/seed_mock_db.py"]]
    if not (RAIZ / "dados" / "indices" / "estrutura.db").exists():
        passos.append(["scripts/indexar_corpus.py"])
    for passo in passos:
        print(f"[preparando] python {' '.join(passo)}")
        subprocess.run([sys.executable, *passo], cwd=RAIZ, check=True)


# ----------------------------------------------------------------------------- impressão

def titulo(texto: str) -> None:
    print("\n" + "=" * LARGURA)
    print(texto)
    print("=" * LARGURA)


def bloco(rotulo: str, texto: str) -> None:
    linhas = []
    for paragrafo in str(texto).splitlines() or [""]:
        linhas += textwrap.wrap(paragrafo, LARGURA - 16) or [""]
    print(f"  {rotulo:<13} {linhas[0]}")
    for linha in linhas[1:]:
        print(f"  {'':<13} {linha}")


def imprimir_turno(r, segundos: float, mostrar_json: bool) -> None:
    s = r.saida
    triagem = r.estado.get("triagem") or {}
    ferramentas = [p["ferramenta"] for p in r.estado.get("trajetoria", []) if p.get("tipo") == "chamada_ferramenta"]
    if triagem.get("rota"):
        bloco("triagem", f"{triagem['rota']} (decidido pelo modelo)")
    bloco("ferramentas", ", ".join(ferramentas) if ferramentas else "nenhuma")
    if s.pergunta_esclarecimento:
        bloco("pergunta", s.pergunta_esclarecimento)
    else:
        bloco("resposta", s.resultado)
    for f in s.fontes:
        bloco("fonte", f"{f.referencia} — {f.detalhe}" if f.detalhe else f.referencia)
    for sup in s.suposicoes:
        bloco("suposição", sup)
    bloco("suficiência", s.suficiencia + (f" ({s.motivo_insuficiencia})" if s.motivo_insuficiencia else ""))
    bloco("término", s.motivo_terminacao)
    for a in s.alertas:
        bloco("alerta", a)
    bloco("tempo", f"{segundos:.1f} s")
    if mostrar_json:
        print(textwrap.indent(json.dumps(s.model_dump(), ensure_ascii=False, indent=2), "    "))


def contar_exports(pasta: Path) -> set[str]:
    return {p.name for p in pasta.glob("*.md")} if pasta.exists() else set()


# ----------------------------------------------------------------------------- cenas

def perguntar_decisao(interacao: dict) -> dict:
    """Decisão do revisor: digitada num terminal interativo, automática fora dele."""
    automatica = {"decisao": "aprovar", "revisor": "demo-automatica", "comentario": "aprovado na demonstração"}
    if not sys.stdin.isatty():
        print("\n  [revisor] aprovação automática (terminal não interativo)")
        return automatica
    while True:
        r = input("\n  [revisor] aprovar, rejeitar ou editar? [a/r/e] ").strip().lower()
        if r in ("a", "aprovar", ""):
            return {**automatica, "revisor": "revisor-demo"}
        if r in ("r", "rejeitar"):
            return {"decisao": "rejeitar", "revisor": "revisor-demo", "comentario": "rejeitado na demonstração"}
        if r in ("e", "editar"):
            nova = input("  [revisor] nova explicação: ").strip() or interacao["argumentos"].get("explicacao", "")
            return {"decisao": "editar", "argumentos": {"explicacao": nova}, "revisor": "revisor-demo",
                    "comentario": "explicação editada na demonstração"}


def rodar_cena(n: int, deps, grafo, rodada: str, mostrar_json: bool, auto: bool) -> None:
    from src.grafo.execucao import executar_turno, retomar
    from src.projects.farmacia_precos.tools_farmacia import PASTA_EXPORTS

    nome, explicacao, perguntas = CENAS[n - 1]
    titulo(f"CENA {n} — {nome}")
    print(textwrap.fill(explicacao, LARGURA))
    usuario, sessao = f"G-DEMO{n}", f"demo{n}-{rodada}"
    antes = contar_exports(PASTA_EXPORTS)

    for i, pergunta in enumerate(perguntas, 1):
        print(f"\n> Gestor: {pergunta}\n")
        t0 = time.perf_counter()
        r = executar_turno(pergunta, deps, usuario, sessao, grafo=grafo)
        imprimir_turno(r, time.perf_counter() - t0, mostrar_json)
        if i < len(perguntas):
            time.sleep(PAUSA_ENTRE_CENAS)

    if r.interrupcao is None:
        if n == 5:
            print("\n  (o modelo não pediu a exportação desta vez; rode a cena de novo)")
        return

    itr = r.interrupcao
    print("\n  --- O grafo PAROU e espera uma pessoa ---")
    bloco("ação", itr["acao"])
    bloco("argumentos", json.dumps(itr["argumentos"], ensure_ascii=False))
    bloco("consequência", itr["consequencia"])
    bloco("prazo", itr["prazo_expira_em"])
    bloco("sem resposta", itr.get("se_ninguem_responder", "a execução expira e nada é exportado"))

    cp_pausa = grafo.get_state({"configurable": {"thread_id": r.thread_id}}).config["configurable"]["checkpoint_id"]
    decisao = {"decisao": "aprovar", "revisor": "demo-automatica", "comentario": "aprovado na demonstração"} if auto else perguntar_decisao(itr)
    if auto:
        print("\n  [revisor] aprovação automática (--auto)")

    t0 = time.perf_counter()
    r1 = retomar(r.thread_id, decisao, deps, grafo)
    print(f"\n> Revisor: {decisao['decisao']}\n")
    imprimir_turno(r1, time.perf_counter() - t0, mostrar_json)
    depois_1 = contar_exports(PASTA_EXPORTS)

    if decisao["decisao"] == "rejeitar":
        bloco("exportações", f"antes: {len(antes)} · depois da rejeição: {len(depois_1)} (nada foi gravado)")
        return

    # A MESMA decisão entregue de novo, a partir do checkpoint da pausa: é o revisor clicando duas
    # vezes, ou o processo caindo depois de exportar. A chave do arquivo é o hash do conteúdo.
    time.sleep(PAUSA_ENTRE_CENAS)
    print("\n> A mesma aprovação chega uma segunda vez (clique duplo / retentativa)\n")
    retomar(r.thread_id, decisao, deps, grafo, checkpoint_id=cp_pausa)
    depois_2 = contar_exports(PASTA_EXPORTS)
    bloco("exportações", f"antes: {len(antes)} · 1ª aprovação: {len(depois_1)} · 2ª aprovação: {len(depois_2)}")
    novos = sorted(depois_2 - antes)
    if novos:
        bloco("arquivo", str((PASTA_EXPORTS / novos[0]).relative_to(RAIZ)))
    elif depois_1 == antes:
        bloco("arquivo", "o mesmo conteúdo já tinha sido exportado antes: nada novo foi criado")


# ----------------------------------------------------------------------------- main

def main() -> None:
    p = argparse.ArgumentParser(description="Demonstração do agente de BI de farmácia.")
    p.add_argument("--cena", type=int, choices=range(1, len(CENAS) + 1), help="roda só esta cena")
    p.add_argument("--pergunta", help="faz uma pergunta livre ao agente")
    p.add_argument("--json", action="store_true", help="mostra também o objeto de saída completo")
    p.add_argument("--auto", action="store_true", help="aprovação automática na cena 5")
    p.add_argument("--sintetico", action="store_true", help="usa o espelho sintético mesmo com o banco real configurado")
    args = p.parse_args()

    preparar_ambiente()

    from src.grafo.execucao import executar_turno, montar_dependencias
    from src.grafo.grafo import obter_grafo
    print("Carregando o modelo de embedding e o grafo...")
    deps, banco = montar_dependencias(pasta_memoria=PASTA_MEMORIA_DEMO)
    grafo = obter_grafo()
    fonte = {"sql_server_real": "banco real do fractal-precos", "espelho_sqlite": "espelho com dados sintéticos"}.get(banco.fonte, banco.fonte)
    print(f"Modelo: {deps.modelo} · dados: {fonte}")
    motivo = getattr(banco, "motivo_fallback", None)
    if motivo:
        causa = "login recusado (confira usuário e senha no .env)" if "Login failed" in motivo else "sem conexão com o servidor"
        print(f"  (o banco real não abriu — {causa}; a demonstração segue no espelho sintético)")
    rodada = datetime.now().strftime("%Y%m%dT%H%M%S")

    try:
        if args.pergunta:
            titulo("PERGUNTA LIVRE")
            print(f"\n> Gestor: {args.pergunta}\n")
            t0 = time.perf_counter()
            r = executar_turno(args.pergunta, deps, "G-DEMO0", f"livre-{rodada}", grafo=grafo)
            imprimir_turno(r, time.perf_counter() - t0, args.json)
            if r.interrupcao:
                print(f"\n  O grafo parou e espera aprovação. Para responder:\n"
                      f"  python -m src.main --retomar {r.thread_id} --decisao aprovar")
            return
        cenas = [args.cena] if args.cena else range(1, len(CENAS) + 1)
        for i, n in enumerate(cenas):
            if i:
                time.sleep(PAUSA_ENTRE_CENAS)
            rodar_cena(n, deps, grafo, rodada, args.json, args.auto)
        print("\nFim da demonstração.")
    finally:
        banco.close()


if __name__ == "__main__":
    main()
