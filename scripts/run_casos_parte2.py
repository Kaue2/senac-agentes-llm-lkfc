"""Os 6 casos demonstrados da Parte 2 (§9) e os exemplos de entrada e saída (§1.3, §1.4), rodados
no grafo de verdade (src/grafo/), com o modelo ATIVO do .env, e gravados em logs/parte2/.

Uso: python scripts/run_casos_parte2.py [--so caso-06 ...]

Condições declaradas da rodada (vão para logs/parte2/resumo.json):
- banco: espelho sintético (a trava `exigir_espelho` impede rodar contra o banco real do cliente);
- memória de longo prazo: VAZIA no início, numa pasta própria (dados/memoria_parte2/), e um gestor
  (`usuario_id`) por caso, para um caso não ver a memória do anterior; o exemplo `io-07-memoria`
  mostra a memória atravessando duas sessões do mesmo gestor;
- checkpoint: o do sistema (dados/checkpoints/grafo.db), com `sessao_id` único por rodada;
- exportações: dados/exports/ (o caso 6 conta os arquivos antes e depois).
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()

from src.grafo.execucao import ResultadoTurno, executar_turno, montar_dependencias, retomar  # noqa: E402
from src.grafo.grafo import obter_grafo  # noqa: E402
from src.projects.farmacia_precos.fabrica import exigir_espelho  # noqa: E402
from src.projects.farmacia_precos.tools_farmacia import PASTA_EXPORTS  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]
PASTA_LOGS = RAIZ / "logs" / "parte2"
PASTA_MEMORIA = RAIZ / "dados" / "memoria_parte2"
PAUSA_ENTRE_CHAMADAS = 8  # segundos: o tier gratuito limita tokens por minuto

# (id, descrição, o que ele prova, turnos). Cada turno: (sessão, texto).
CASOS = [
    ("caso-01-simples", "Caso simples", "o caminho feliz existe (§1.3)",
     [("c01", "Qual o preço atual da Novalgina 500mg na farmácia Araujo?")]),
    ("caso-02-divergencia", "Divergência", "o sistema diz uma coisa, o usuário diz outra (§1.4)",
     [("c02", "Tenho certeza que a Drogasil vende a Trayenta 5mg por R$150. Por que seu relatório mostra outro valor?")]),
    ("caso-03-registro-inexistente", "Registro inexistente", "erro de ferramenta que o modelo contorna (§3.2)",
     [("c03", "Qual o preço da Ivermectina 6mg na farmácia Extrafarma?")]),
    ("caso-04-nao-deve-agir", "Não deve disparar a ação principal", "o sistema sabe não agir: não chama exportar_analise nem pausa (§3.3)",
     [("c04", "O Ozempic 1mg está em falta em alguma farmácia? Desde quando?")]),
    ("caso-05-fora-do-corpus", "Pergunta fora do corpus", "o sistema recusa, e recusa dizendo algo útil (§1.2)",
     [("c05", "Qual é a política de troca e devolução de produtos para o cliente final?")]),
    ("io-01-incompleta", "Entrada incompleta (2 turnos)", "pergunta o que falta e, com a resposta, atende (§1.4)",
     [("io1", "quanto ta o remedio na drogasil?"), ("io1", "a trayenta 5mg")]),
    ("io-02-ambigua", "Entrada ambígua", "escolhe e declara a escolha (§1.4)",
     [("io2", "quanto custa a trayenta na raia")]),
    ("io-03-fora-do-escopo", "Entrada fora do escopo", "recusa e diz o que faz (§1.4)",
     [("io3", "quantas caixas de clonazepam o cliente de cpf 123.456.789-09 comprou esse mes?")]),
    ("io-04-regra-com-citacao", "Pergunta de regra (RAG como ferramenta)", "o modelo decide buscar e cita o trecho (§4.4)",
     [("io4", "O desconto do PBM conta para o teto de desconto da rede?")]),
    ("io-07-memoria", "Memória entre execuções (2 sessões)", "a preferência declarada numa sessão muda a próxima (§5)",
     [("io7a", "Minha farmácia padrão é a Raia. Qual o preço da Novalgina 500mg lá?"), ("io7b", "qual o preço atual da Trayenta 5mg?")]),
]

DECISAO_EDITADA = {
    "decisao": "editar",
    "argumentos": {"explicacao": "Preço de farmácia (sem PBM) coletado em 19/09/2026. Revisado pela Administração para a reunião de diretoria."},
    "revisor": "administracao-01",
    "comentario": "explicação ajustada para a diretoria",
}


def usuario_do_caso(id_: str) -> str:
    """Um gestor por caso: a memória de um caso não vaza para o seguinte, e cada log se reproduz
    sozinho. Os turnos de um mesmo caso (io-01, io-07) compartilham o gestor — é o que eles mostram."""
    return "G-" + id_.split("-", 1)[0].upper()[:2] + id_.split("-")[1]


def resumo_turno(r: ResultadoTurno) -> dict:
    ferramentas = [p["ferramenta"] for p in r.estado.get("trajetoria", []) if p.get("tipo") == "chamada_ferramenta"]
    log = json.loads(r.caminho_log.read_text(encoding="utf-8")) if r.caminho_log else {}
    return {
        "thread_id": r.thread_id, "turno": r.saida.turno, "suficiencia": r.saida.suficiencia,
        "motivo_terminacao": r.saida.motivo_terminacao, "ferramentas": ferramentas,
        "fontes": [f.referencia for f in r.saida.fontes], "pausou": r.interrupcao is not None,
        "medicoes": log.get("medicoes"), "log": str(r.caminho_log.relative_to(RAIZ)) if r.caminho_log else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--so", nargs="*", help="Roda só os casos cujo id começa com estes prefixos.")
    args = parser.parse_args()

    shutil.rmtree(PASTA_MEMORIA, ignore_errors=True)
    deps, banco = montar_dependencias(memoria=True, pasta_memoria=PASTA_MEMORIA)
    exigir_espelho(banco)
    grafo = obter_grafo()
    rodada = datetime.now().strftime("%Y%m%dT%H%M%S")
    PASTA_LOGS.mkdir(parents=True, exist_ok=True)
    resumo: dict = {"rodada": rodada, "condicoes": __doc__.split("Condições declaradas da rodada")[1].strip(), "casos": {}}

    try:
        for id_, descricao, prova, turnos in CASOS:
            if args.so and not any(id_.startswith(p) for p in args.so):
                continue
            print(f"\n=== {id_} — {descricao} ===")
            registros = []
            for i, (sessao, texto) in enumerate(turnos, start=1):
                r = executar_turno(texto, deps, usuario_do_caso(id_), f"{sessao}-{rodada}", grafo=grafo,
                                   pasta_logs=PASTA_LOGS, nome_log=f"{id_}-t{i}.json")
                print(f"> {texto}\n{r.saida.resultado}\n[{r.saida.suficiencia} | {r.saida.motivo_terminacao}]")
                registros.append(resumo_turno(r))
                time.sleep(PAUSA_ENTRE_CHAMADAS)
            resumo["casos"][id_] = {"descricao": descricao, "prova": prova, "turnos": registros}

        if not args.so or any("caso-06".startswith(p) or p.startswith("caso-06") for p in args.so):
            print("\n=== caso-06-para-e-espera — A ação que para e espera ===")
            antes = sorted(p.name for p in PASTA_EXPORTS.glob("*.md")) if PASTA_EXPORTS.exists() else []
            texto = "Qual o preço da Trayenta 5mg na Drogasil? Salva essa análise pra eu mandar pra diretoria."
            r0 = executar_turno(texto, deps, usuario_do_caso("caso-06"), f"c06-{rodada}", grafo=grafo, pasta_logs=PASTA_LOGS, nome_log="caso-06-t1-pausa.json")
            print(f"> {texto}\n{r0.saida.resultado}\n[{r0.saida.suficiencia}]")
            if r0.interrupcao is None:
                print("!! o grafo não pausou — o modelo não pediu a exportação nesta execução")
                resumo["casos"]["caso-06-para-e-espera"] = {"falhou": "não pausou", "turno": resumo_turno(r0)}
            else:
                cp_pausa = grafo.get_state({"configurable": {"thread_id": r0.thread_id}}).config["configurable"]["checkpoint_id"]
                time.sleep(PAUSA_ENTRE_CHAMADAS)
                r1 = retomar(r0.thread_id, DECISAO_EDITADA, deps, grafo, pasta_logs=PASTA_LOGS, nome_log="caso-06-t1-aprovacao-1.json")
                meio = sorted(p.name for p in PASTA_EXPORTS.glob("*.md"))
                print(f"[aprovação 1] {r1.saida.acoes_executadas[0].model_dump() if r1.saida.acoes_executadas else 'nenhuma ação'}")
                time.sleep(PAUSA_ENTRE_CHAMADAS)
                # A MESMA aprovação entregue de novo, a partir do mesmo checkpoint da pausa: é o que
                # acontece quando o revisor clica duas vezes ou o processo cai depois de exportar e
                # antes de gravar o checkpoint seguinte.
                r2 = retomar(r0.thread_id, DECISAO_EDITADA, deps, grafo, checkpoint_id=cp_pausa,
                             pasta_logs=PASTA_LOGS, nome_log="caso-06-t1-aprovacao-2-repetida.json")
                depois = sorted(p.name for p in PASTA_EXPORTS.glob("*.md"))
                print(f"[aprovação 2] {r2.saida.acoes_executadas[0].model_dump() if r2.saida.acoes_executadas else 'nenhuma ação'}")
                resumo["casos"]["caso-06-para-e-espera"] = {
                    "descricao": "A ação que para e espera", "prova": "pausa, aprovação editando, a segunda aprovação não duplica (§8.2, §8.5)",
                    "checkpoint_da_pausa": cp_pausa,
                    "turnos": [resumo_turno(r0), resumo_turno(r1), resumo_turno(r2)],
                    "exports_antes": antes, "exports_depois_aprovacao_1": meio, "exports_depois_aprovacao_2": depois,
                    "arquivos_novos_aprovacao_1": sorted(set(meio) - set(antes)),
                    "arquivos_novos_aprovacao_2": sorted(set(depois) - set(meio)),
                    "ja_existia": [r.saida.acoes_executadas[0].ja_existia if r.saida.acoes_executadas else None for r in (r1, r2)],
                }
    finally:
        banco.close()
        nome_resumo = "resumo.json" if not args.so else f"resumo-{'-'.join(args.so)}.json"
        (PASTA_LOGS / nome_resumo).write_text(json.dumps(resumo, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n[resumo: logs/parte2/{nome_resumo}]")


if __name__ == "__main__":
    main()
