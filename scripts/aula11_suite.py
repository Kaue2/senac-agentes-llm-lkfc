"""Exercício 11 — a suíte do case: versão A (agente v1) × versão B (v2, RAG como ferramenta).

Uso:
    python scripts/aula11_suite.py                 # roda o que falta e imprime o relatório
    python scripts/aula11_suite.py --so-relatorio  # não chama o modelo; só lê o que já rodou

Retomável (src/evals/suite.py): se o limite diário do provedor estourar, rode de novo no dia
seguinte — o que já rodou não é refeito. Saída em logs/aula11/saida.txt.

Parâmetros e justificativas:
- `REPETICOES = 2`: o mínimo do enunciado. Com 24 casos, 2 repetições × 2 versões já são ~96
  execuções do agente (~2–3 mil tokens cada), perto do limite diário gratuito; a terceira
  repetição dobraria o custo para estreitar uma estimativa de ruído que a regra já absorve com
  o piso de 5 p.p.
- Ordem de execução: A rep1, A rep2, B rep1, B rep2 — o ruído de base (A × A) fica pronto antes
  de qualquer resultado de B, como pede o §5.
- A temperatura do agente NÃO é fixada (padrão do provedor), de propósito: a suíte mede o
  sistema como ele roda; o ruído de amostragem é medido (ruído de base), não escondido.
- A suíte roda SEM memória de longo prazo (estado: vazia) e sobre o espelho SQLite fixo: as duas
  fontes de não determinismo controláveis estão congeladas; só a amostragem varia.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv

load_dotenv()

import openai  # noqa: E402

from src.core.llm_client import cliente_ativo_ou_none  # noqa: E402
from src.evals import regra  # noqa: E402
from src.evals.dataset import DATASET_VERSAO, carregar_dataset, hash_dataset, resumo  # noqa: E402
from src.evals.juiz import LIMIAR_ADOCAO, MINIMO_ROTULOS, concordancia, ler_rotulos  # noqa: E402
from src.evals.suite import (  # noqa: E402
    caminho_execucao,
    executar_caso,
    pass_k,
    propriedade_pass_k,
    taxa,
    taxas_por_classe,
)
from src.projects.farmacia_precos import config  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]
REPETICOES = 2
VERSOES = {"A": "v1", "B": "v2"}

_linhas: list[str] = []


def out(texto: str = "") -> None:
    print(texto)
    _linhas.append(texto)


def rodar(casos, so_relatorio: bool) -> dict[tuple[str, int], list[dict]]:
    import json

    registros: dict[tuple[str, int], list[dict]] = {}
    agentes = {}
    for rotulo, versao in VERSOES.items():
        for rep in range(1, REPETICOES + 1):
            lista = []
            for caso in casos:
                destino = caminho_execucao(versao, rep, caso.id)
                if destino.exists():
                    lista.append(json.loads(destino.read_text(encoding="utf-8")))
                    continue
                if so_relatorio:
                    continue
                if versao not in agentes:
                    from src.projects.farmacia_precos.fabrica import exigir_espelho, montar_agente

                    agente, banco, _ = montar_agente(versao)
                    exigir_espelho(banco)
                    agentes[versao] = agente
                print(f"  rodando {rotulo}/{versao} rep{rep} {caso.id}...", flush=True)
                try:
                    lista.append(executar_caso(agentes[versao], caso, versao, rep))
                except (openai.RateLimitError, openai.APIConnectionError, openai.APIStatusError) as exc:
                    print(f"\nInterrompido por erro de infraestrutura ({type(exc).__name__}): {exc}")
                    print("O que já rodou está gravado; rode o script de novo para continuar.")
                    raise SystemExit(2)
            registros[(rotulo, rep)] = lista
    return registros


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--so-relatorio", action="store_true")
    args = parser.parse_args()

    cliente, modelo_llm = cliente_ativo_ou_none()
    if cliente is None and not args.so_relatorio:
        raise SystemExit(f"Este exercício precisa do LLM: {modelo_llm}")

    casos = carregar_dataset()
    r = resumo(casos)
    out(f"DATASET v{DATASET_VERSAO} (sha256 {hash_dataset()})   {len(casos)} casos")
    out("  por origem:   " + "   ".join(f"{o} {r['por_origem'].get(o, 0)}" for o in ("producao", "desenvolvimento", "sintetico")))
    out("  por classe:   " + "  ".join(f"{c} {n}" for c, n in sorted(r["por_classe"].items())))
    if r["sinteticos_sem_revisao"]:
        out(f"  sintéticos sem revisão humana: {', '.join(r['sinteticos_sem_revisao'])}")

    registros = rodar(casos, args.so_relatorio)
    completos = all(len(v) == len(casos) for v in registros.values())

    # --------------------------------------------------------- validação do juiz
    rotulos = ler_rotulos()
    c = concordancia(rotulos)
    out("\nVALIDAÇÃO DO JUIZ (rubrica juiz_fundamentacao_v1.0)")
    if c.n == 0:
        out(f"  sem rótulos humanos ainda (dados/avaliacao/rotulos_juiz_v1.csv): rode scripts/aula11_rotular.py")
        out("  VEREDITO: não adotado — o juiz não entra na regra de promoção")
    else:
        out("                    humano: sim   humano: não")
        out(f"    juiz: sim            {c.juiz_sim_humano_sim:3d}          {c.juiz_sim_humano_nao:3d}")
        out(f"    juiz: não            {c.juiz_nao_humano_sim:3d}          {c.juiz_nao_humano_nao:3d}")
        veredito = "adotar" if c.adotado else "não adotar"
        if c.n < MINIMO_ROTULOS:
            veredito += f" (só {c.n} rótulos; mínimo {MINIMO_ROTULOS})"
        out(f"  concordância: {100 * c.taxa:.1f}%   limiar declarado: {100 * LIMIAR_ADOCAO:.0f}%   VEREDITO: {veredito}")
        desacordos = [l for l in rotulos if l.get("rotulo_humano", "").strip() and l["veredito_juiz"] != l["rotulo_humano"].strip().lower().replace("não", "nao")]
        tipos = {t: sum(1 for l in desacordos if l.get("classificacao_desacordo", "").strip() == t) for t in ("juiz", "rubrica", "rotulo")}
        out(f"  desacordos: {len(desacordos)}  (juiz {tipos['juiz']} · rubrica {tipos['rubrica']} · rótulo {tipos['rotulo']}"
            f" · não classificados {len(desacordos) - sum(tipos.values())})")

    # --------------------------------------------------------- ruído e suíte
    a1, a2 = registros.get(("A", 1), []), registros.get(("A", 2), [])
    out("\nRUÍDO DE BASE")
    if len(a1) == len(a2) == len(casos):
        ruido = abs(100 * (taxa(a1) - taxa(a2)))
        viradas = [x["caso_id"] for x, y in zip(a1, a2) if x["passou"] != y["passou"]]
        out(f"  versão A, execuções: {100 * taxa(a1):.1f}%, {100 * taxa(a2):.1f}%   dispersão: {ruido:.1f} pontos")
        out(f"  casos que viraram entre as duas execuções de A: {', '.join(viradas) or 'nenhum'}")
    else:
        ruido = None
        out(f"  incompleto: A rep1 {len(a1)}/{len(casos)}, A rep2 {len(a2)}/{len(casos)}")

    todos_a = a1 + a2
    todos_b = registros.get(("B", 1), []) + registros.get(("B", 2), [])
    out("\nSUÍTE  (taxa de casos aprovados, média das repetições; juiz fora enquanto não adotado)")
    if completos and ruido is not None:
        ca, cb = taxas_por_classe(todos_a), taxas_por_classe(todos_b)
        out(f"  {'classe':18s}{'A':>8s}{'B':>8s}{'delta':>9s}")
        for classe in ca:
            out(f"  {classe:18s}{100 * ca[classe]:7.1f}%{100 * cb[classe]:7.1f}%{100 * (cb[classe] - ca[classe]):+8.1f}")
        out(f"  {'MÉDIA':18s}{100 * taxa(todos_a):7.1f}%{100 * taxa(todos_b):7.1f}%{100 * (taxa(todos_b) - taxa(todos_a)):+8.1f}")
        pk_a, pk_b = pass_k(todos_a), pass_k(todos_b)
        out(f"  pass^{REPETICOES}: A {sum(pk_a.values())}/{len(pk_a)}   B {sum(pk_b.values())}/{len(pk_b)}")
        out(f"  tokens médios por execução: A {sum(x['tokens'] for x in todos_a) / len(todos_a):.0f}"
            f"   B {sum(x['tokens'] for x in todos_b) / len(todos_b):.0f}")
        criticas = {f"classe {cl}": all(pk_b[x["caso_id"]] for x in todos_b if x["classe"] == cl) for cl in regra.CLASSES_CRITICAS}
        criticas.update({f"propriedade {p}": propriedade_pass_k(todos_b, p) for p in regra.PROPRIEDADES_CRITICAS})
        decisao = regra.aplicar(taxa(todos_a), taxa(todos_b), ruido, ca, cb, criticas)
        out(f"\nDECISÃO: {'promover' if decisao.promover else 'não promover'}")
        out(f"  regra aplicada (v{regra.VERSAO_REGRA}, declarada em {regra.DECLARADA_EM}): {regra.TEXTO}")
        for m in decisao.motivos:
            out(f"  {m}")
        falhas_b = sorted({x["caso_id"] for x in todos_b if not x["passou"]})
        falhas_a = sorted({x["caso_id"] for x in todos_a if not x["passou"]})
        out(f"\n  casos com alguma falha — A: {', '.join(falhas_a) or 'nenhum'}")
        out(f"  casos com alguma falha — B: {', '.join(falhas_b) or 'nenhum'}")
    else:
        out("  incompleto — " + ", ".join(f"{k[0]}{k[1]} {len(v)}/{len(casos)}" for k, v in registros.items()))

    out("\nCARIMBO")
    carimbo = [
        ("prompt do agente", "A: analista_bi_v1 (prompts/) · B: analista_bi@v2.0 (src/prompts/)"),
        ("modelo", modelo_llm if cliente is not None else "(não carregado: --so-relatorio sem .env)"),
        ("parâmetros", f"temperature padrão do provedor · max_passos {config.max_passos()} · max_tokens {config.max_tokens()}"),
        ("chunking", "estrutura (seção ##, herda título) — só B"),
        ("modelo de embedding", "fastembed:intfloat/multilingual-e5-large — só B"),
        ("métrica / k / limiar", "cosseno · k=3 · 0,1685 · somente vigentes — só B"),
        ("extração de documento", "não se aplica: corpus nasce em Markdown, sem PDF"),
        ("prompt de resposta RAG", "não usado pelo agente (B usa a busca como ferramenta; resposta_rag_v1 é do Ex. 7)"),
        ("estado da memória", "vazia (a suíte não liga a memória do Ex. 8)"),
        ("servidor MCP", "não usado pelo agente (o servidor do Ex. 10 é CNPJ/CEP, fora do laço)"),
        ("dataset", f"golden_v1.jsonl v{DATASET_VERSAO} sha256 {hash_dataset()}"),
        ("rubrica do juiz", "juiz_fundamentacao_v1.0 · modelo em JUDGE_MODEL"),
        ("regra de promoção", f"v{regra.VERSAO_REGRA} declarada em {regra.DECLARADA_EM}"),
    ]
    for chave, valor in carimbo:
        out(f"  {chave} {'.' * max(2, 24 - len(chave))} {valor}")

    pasta = RAIZ / "logs" / "aula11"
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "saida.txt").write_text("\n".join(_linhas) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
