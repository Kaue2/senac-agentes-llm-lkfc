"""Exercício 7 (complementar) — a resposta que cita, e que recusa.

Uso: python scripts/aula07_resposta_que_cita.py

Pré-requisitos: índice da Aula 06 (python scripts/aula06_buscador.py) e LLM no .env.
Grava a saída em logs/aula07/saida.txt e todos os traces em logs/aula07/resposta_que_cita.json.

Parâmetros e justificativas:
- `k` e `limiar` vêm da Aula 06 (src/rag/resposta.py: K_PADRAO, LIMIAR_PADRAO) — trocar
  qualquer um invalida a comparação com aquele relatório.
- A rodada principal usa o índice SEM curadoria (o documento revogado de 2025 está nele), de
  propósito: é a rodada que mede o §6. A rodada com curadoria (`somente_vigentes`) vem depois,
  só nas perguntas afetadas.
- `K_CONTEXTO_LONGO = 9`, `POSICAO_MEIO = 5`: para o modo de falha "recuperou e ignorou", o
  trecho certo é posto no meio de nove — a posição que a literatura de "lost in the middle"
  aponta como a mais ignorada. `MAX_TENTATIVAS_IGNOROU = 6` limita o custo da busca pela falha.
- `LIMIARES_CURVA`: pontos em torno do limiar calibrado, para mostrar a troca entre os dois erros.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv

load_dotenv()

from src.core.llm_client import cliente_ativo_ou_none  # noqa: E402
from src.rag.avaliacao import carregar_perguntas, trecho_contem_evidencia  # noqa: E402
from src.rag.embeddings import modelo_do_ambiente  # noqa: E402
from src.rag.indice import PASTA_INDICES, IndiceVetorial, Resultado, somente_vigentes  # noqa: E402
from src.rag.juiz_rag import JuizRAG  # noqa: E402
from src.rag.resposta import K_PADRAO, LIMIAR_PADRAO, PipelineRAG  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]
PASTA_LOG = RAIZ / "logs" / "aula07"
K_CONTEXTO_LONGO = 9
POSICAO_MEIO = 5
MAX_TENTATIVAS_IGNOROU = 6
PERGUNTAS_ORDEM = 3
LIMIARES_CURVA = [0.160, 0.163, 0.1655, 0.1685, 0.170, 0.175, 0.200]
# Perguntas cuja resposta tem versão revogada no corpus (política 2025 × 2026) — §6.
PERGUNTAS_COM_VERSAO_REVOGADA = ("Q01", "Q10", "Q12")

_linhas: list[str] = []


def out(texto: str = "") -> None:
    print(texto)
    _linhas.append(texto)


def resumo(r) -> dict:
    return {
        "resposta": r.resposta,
        "recusou": r.recusou,
        "barrado_pelo_portao": r.barrado_pelo_portao,
        "citacoes": r.citacoes,
        "citacoes_invalidas": r.citacoes_invalidas,
        "trace": r.trace,
    }


def main() -> None:
    cliente, modelo_llm = cliente_ativo_ou_none()
    if cliente is None:
        raise SystemExit(f"Este exercício precisa do LLM: {modelo_llm}")

    indice = IndiceVetorial.carregar(PASTA_INDICES / "estrutura.db")
    embeddings = modelo_do_ambiente()
    if embeddings.nome != indice.carimbo["modelo_embedding"]:
        raise SystemExit(
            f"Índice construído com {indice.carimbo['modelo_embedding']} e consulta com {embeddings.nome}: "
            "vetores de modelos diferentes não são comparáveis. Reindexe (scripts/aula06_buscador.py)."
        )
    perguntas = carregar_perguntas()
    por_id = {p.id: p for p in perguntas}
    juiz = JuizRAG(cliente, modelo_llm)
    pipeline = PipelineRAG(indice, embeddings, cliente, modelo_llm, k=K_PADRAO, limiar=LIMIAR_PADRAO)
    registro: dict = {"executado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"), "casos": {}}

    out("PIPELINE")
    out(f"  k={pipeline.k}   limiar={pipeline.limiar:.4f}   prompt de resposta {pipeline.prompt.versao}"
        f"   juiz {juiz.modelo} ({juiz.prompt.rotulo})")

    # --------------------------------------------------------- rodada principal
    linhas_diag = []
    total_citacoes = citacoes_validas = 0
    fieis = julgadas = 0
    recall_ok = com_resposta = 0
    recusas_corretas = recusas_indevidas = 0
    sem_resposta = [p for p in perguntas if not p.tem_resposta]
    for p in perguntas:
        r = pipeline.responder(p.pergunta)
        caso: dict = {"pergunta": p.pergunta, "rodada_principal": resumo(r)}
        veredito = None
        if not r.barrado_pelo_portao and r.trace.get("decisao") != "erro_contrato":
            veredito = juiz.julgar(r, p.resposta_referencia)
            caso["juiz"] = veredito.__dict__
            if veredito.fiel is not None:
                julgadas += 1
                fieis += int(veredito.fiel)
        total_citacoes += len(r.citacoes)
        citacoes_validas += len(r.citacoes_validas)

        if p.tem_resposta:
            com_resposta += 1
            recuperou = any(trecho_contem_evidencia(x.trecho, p) for x in r.recuperados)
            recall_ok += int(recuperou)
            if r.recusou:
                recusas_indevidas += 1
            if not recuperou:
                onde = "índice"
            elif r.recusou:
                onde = "portão" if r.barrado_pelo_portao else "prompt (recusa indevida)"
            elif veredito is None or veredito.fiel is None:
                onde = "erro de contrato"
            elif not veredito.fiel:
                onde = "prompt"
            elif not veredito.correta:
                onde = "corpus"
            else:
                onde = "ok"
            fid = "—" if veredito is None or veredito.fiel is None else ("ok" if veredito.fiel else "falhou")
            linhas_diag.append(f"  {p.id}  recall {'ok' if recuperou else 'falhou':6s}  fidelidade {fid:6s}  -> {onde}")
        else:
            recusas_corretas += int(r.recusou)
            onde = "ok (recusou)" if r.recusou else "respondeu sem base"
            linhas_diag.append(f"  {p.id}  sem resposta no corpus  recusou={r.recusou}  -> {onde}")
        caso["diagnostico"] = onde
        registro["casos"][p.id] = caso

    out(f"\nMÉTRICAS ({len(perguntas)} perguntas; índice sem curadoria)")
    out(f"  recall@k ................. {100 * recall_ok / com_resposta:.1f}%  ({recall_ok}/{com_resposta})")
    if total_citacoes:
        out(f"  citações verificáveis .... {100 * citacoes_validas / total_citacoes:.1f}%  ({citacoes_validas}/{total_citacoes})")
    out(f"  fidelidade ............... {100 * fieis / max(julgadas, 1):.1f}%  ({fieis}/{julgadas}; juiz NÃO validado — ver Aula 11)")
    out(f"  recusas corretas ......... {recusas_corretas}/{len(sem_resposta)}")
    out(f"  recusas indevidas ........ {recusas_indevidas}/{com_resposta}")
    out("\nDIAGNÓSTICO POR PERGUNTA")
    for linha in linhas_diag:
        out(linha)

    # ------------------------------------------- controle do juiz (dica do enunciado)
    # "Se a sua fidelidade está em 100%, verifique se o juiz está medindo alguma coisa": respostas
    # ADULTERADAS de propósito, sobre os mesmos trechos recuperados, que o juiz precisa reprovar.
    from dataclasses import replace

    controles = [
        ("Q01", "O teto é de 25% sobre o PrecoTabela, aprovado pela diretoria [politica-precificacao-2026#s02].",
         False, False, "número trocado"),
        ("Q09", "A coleta roda entre 02:00 e 06:00, horário de Brasília, e de novo às 14:00 aos sábados.",
         False, True, "certa, com um fato a mais inventado"),
        ("Q12", "18% sobre o preço líquido.", True, True, "controle positivo"),
    ]
    out("\nCONTROLE DO JUIZ (respostas adulteradas de propósito)")
    registro["controle_juiz"] = []
    acertos_controle = 0
    for pid, adulterada, fiel_esperado, correta_esperado, descricao in controles:
        base = pipeline.recuperar(por_id[pid].pergunta)
        falsa = replace(pipeline.gerar(por_id[pid].pergunta, base), resposta=adulterada)
        v = juiz.julgar(falsa, por_id[pid].resposta_referencia)
        ok = v.fiel == fiel_esperado and v.correta == correta_esperado
        acertos_controle += int(ok)
        out(f"  {pid} {descricao:38s} esperado fiel={fiel_esperado} correta={correta_esperado}"
            f" | juiz fiel={v.fiel} correta={v.correta}  {'ok' if ok else 'ERROU'}")
        registro["controle_juiz"].append({"id": pid, "resposta": adulterada, "juiz": v.__dict__, "ok": ok})
    out(f"  o juiz acertou {acertos_controle}/{len(controles)} controles")

    # ------------------------------------------- curva do limiar (dois erros)
    out("\nLIMIAR — os dois erros (falso positivo: respondeu quando devia recusar; falso negativo: recusou podendo responder)")
    distancias = {p.id: pipeline.recuperar(p.pergunta, k=1)[0].distancia for p in perguntas}
    sem_portao = {}
    for p in sem_resposta:
        sem_portao[p.id] = pipeline.responder(p.pergunta, portao=False)
        registro["casos"][p.id]["portao_desligado"] = resumo(sem_portao[p.id])
    out(f"  {'limiar':>8s}  {'falso positivo':>15s}  {'falso negativo':>15s}")
    for limiar in LIMIARES_CURVA:
        fp = sum(1 for p in sem_resposta if distancias[p.id] <= limiar and not sem_portao[p.id].recusou)
        fn = sum(1 for p in perguntas if p.tem_resposta and distancias[p.id] > limiar)
        marca = "   <- escolhido" if abs(limiar - pipeline.limiar) < 1e-9 else ""
        out(f"  {limiar:8.4f}  {fp:>12d}/{len(sem_resposta)}  {fn:>12d}/{com_resposta}{marca}")
    out("  sem portão, o modelo recusou sozinho: "
        + ", ".join(f"{pid}={'sim' if r.recusou else 'NÃO'}" for pid, r in sem_portao.items()))

    # --------------------------------------------------- efeito da ordem
    out("\nORDEM DO CONTEXTO")
    candidatos = [p for p in perguntas if p.tem_resposta and registro["casos"][p.id]["diagnostico"] == "ok"]
    registro["ordem"] = []
    for p in candidatos[:PERGUNTAS_ORDEM]:
        invertida = pipeline.responder(p.pergunta, ordem="invertida")
        v = juiz.julgar(invertida, p.resposta_referencia)
        out(f"  {p.id} relevância: correta | invertida: {'correta' if v.correta else 'ERRADA'}"
            f"  citações {invertida.citacoes}")
        registro["ordem"].append({"id": p.id, "invertida": resumo(invertida), "juiz": v.__dict__})

    # --------------------------------------------------- os quatro modos de falha
    out("\nMODOS DE FALHA REPRODUZIDOS")
    nao_recuperou = [pid for pid, c in registro["casos"].items() if c["diagnostico"] == "índice"]
    out(f"  não recuperou ......... {', '.join(f'{pid} «{por_id[pid].pergunta}»' for pid in nao_recuperou) or 'não reproduzido'}")
    for pid in nao_recuperou:
        out(f"      trace: {[x['id'] for x in registro['casos'][pid]['rodada_principal']['trace']['recuperados']]}")

    ignorou = None
    registro["ignorou_tentativas"] = []
    for p in candidatos[:MAX_TENTATIVAS_IGNOROU]:
        longos = pipeline.recuperar(p.pergunta, k=K_CONTEXTO_LONGO)
        certo = next((x for x in longos if trecho_contem_evidencia(x.trecho, p)), None)
        if certo is None:
            continue
        outros = [x for x in longos if x is not certo]
        contexto = outros[: POSICAO_MEIO - 1] + [certo] + outros[POSICAO_MEIO - 1 :]
        contexto = [Resultado(x.trecho, x.distancia, i) for i, x in enumerate(contexto, start=1)]
        r = pipeline.gerar(p.pergunta, contexto)
        v = juiz.julgar(r, p.resposta_referencia)
        registro["ignorou_tentativas"].append({"id": p.id, "resultado": resumo(r), "juiz": v.__dict__})
        if v.correta is False:
            ignorou = (p, r)
            break
    if ignorou:
        out(f"  recuperou e ignorou ... {ignorou[0].id} «{ignorou[0].pergunta}»   (posição do trecho: {POSICAO_MEIO} de {K_CONTEXTO_LONGO})")
        out(f"      resposta: {ignorou[1].resposta}")
    else:
        out(f"  recuperou e ignorou ... não reproduzido em {len(registro['ignorou_tentativas'])} tentativas "
            f"(trecho certo na posição {POSICAO_MEIO} de {K_CONTEXTO_LONGO})")

    contradisse = [pid for pid, c in registro["casos"].items()
                   if c.get("juiz", {}).get("fiel") is False and por_id[pid].tem_resposta]
    out(f"  contradisse ........... {', '.join(contradisse) or 'não reproduzido na rodada principal'}")
    for pid in contradisse:
        out(f"      {registro['casos'][pid]['juiz']['justificativa']}")

    sem_base = [pid for pid, r in sem_portao.items() if not r.recusou]
    out(f"  respondeu sem base .... {', '.join(f'{pid} (portão desligado)' for pid in sem_base) or 'não reproduzido: o modelo recusou mesmo sem portão'}")
    for pid in sem_base:
        out(f"      {sem_portao[pid].resposta}")

    # --------------------------------------------------- corpus desatualizado
    out("\nCORPUS DESATUALIZADO")
    curado = PipelineRAG(indice, embeddings, cliente, modelo_llm, k=K_PADRAO, limiar=LIMIAR_PADRAO,
                         filtro=somente_vigentes, nome_filtro="somente_vigentes")
    registro["corpus_desatualizado"] = []
    for pid in PERGUNTAS_COM_VERSAO_REVOGADA:
        p = por_id[pid]
        caso = registro["casos"][pid]
        ids = [x["id"] for x in caso["rodada_principal"]["trace"]["recuperados"]]
        revogado_no_contexto = any(i.startswith("politica-precificacao-2025") for i in ids)
        correta_sem = caso.get("juiz", {}).get("correta")
        r = curado.responder(p.pergunta)
        v = juiz.julgar(r, p.resposta_referencia)
        out(f"  {pid} documento revogado no contexto: {'sim' if revogado_no_contexto else 'não'}"
            f" | sem curadoria: {'correta' if correta_sem else 'ERRADA'}"
            f" | com filtro somente_vigentes: {'correta' if v.correta else 'ERRADA'}")
        out(f"      sem curadoria: {caso['rodada_principal']['resposta']}")
        registro["corpus_desatualizado"].append(
            {"id": pid, "revogado_no_contexto": revogado_no_contexto, "correta_sem_curadoria": correta_sem,
             "com_curadoria": resumo(r), "juiz_com_curadoria": v.__dict__}
        )
    detectou = all(c["correta_sem_curadoria"] for c in registro["corpus_desatualizado"])
    out(f"  documento revogado: politica-precificacao-2025   o sistema {'detectou' if detectou else 'NÃO detectou'}"
        " (sem o filtro de metadado)")

    carimbo = {**pipeline.carimbo(), **juiz.carimbo(), "filtro_corpus_producao": "somente_vigentes"}
    out("\nCARIMBO")
    for chave, valor in carimbo.items():
        out(f"  {chave} {'.' * max(2, 24 - len(chave))} {valor}")
    registro["carimbo"] = carimbo

    PASTA_LOG.mkdir(parents=True, exist_ok=True)
    (PASTA_LOG / "resposta_que_cita.json").write_text(
        json.dumps(registro, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    (PASTA_LOG / "saida.txt").write_text("\n".join(_linhas) + "\n", encoding="utf-8")
    out("\n[log em logs/aula07/resposta_que_cita.json; saída em logs/aula07/saida.txt]")


if __name__ == "__main__":
    main()
