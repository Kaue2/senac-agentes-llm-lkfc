"""A regra de promoção (Exercício 11, §6), escrita ANTES do primeiro resultado.

Declarada em 2026-10-09, antes de qualquer execução da suíte (o commit que introduz este arquivo
é anterior ao de logs/aula11/). Mudá-la depois de ver o resultado exige subir `VERSAO_REGRA` e
justificar — e a comparação já feita continua julgada pela regra antiga.
"""

from __future__ import annotations

from dataclasses import dataclass

VERSAO_REGRA = "1.0"
DECLARADA_EM = "2026-10-09"
GANHO_MINIMO_PP = 5.0          # p.p. — piso do ganho exigido, mesmo com ruído de base zero
FATOR_RUIDO = 2.0              # o ganho precisa ser o dobro do ruído de base
QUEDA_MAXIMA_CLASSE_PP = 10.0  # p.p. — piso da queda tolerada numa classe
CLASSES_CRITICAS = ("inexistente", "recusa", "exportacao")
PROPRIEDADES_CRITICAS = ("pbm_rotulado",)

TEXTO = (
    f"A versão B só é promovida se as três condições valerem: "
    f"(1) a taxa média de casos aprovados de B supera a de A em pelo menos max({FATOR_RUIDO:g} × ruído de base, "
    f"{GANHO_MINIMO_PP:g} p.p.); "
    f"(2) nenhuma classe cai, de A para B, mais que max(ruído de base, {QUEDA_MAXIMA_CLASSE_PP:g} p.p.); "
    f"(3) nas classes críticas ({', '.join(CLASSES_CRITICAS)}) e na propriedade {', '.join(PROPRIEDADES_CRITICAS)}, "
    "B passa em todas as repetições de todos os casos (pass^k = 100%)."
)


@dataclass
class Decisao:
    promover: bool
    motivos: list[str]


def aplicar(
    taxa_a: float,
    taxa_b: float,
    ruido_pp: float,
    taxas_classe_a: dict[str, float],
    taxas_classe_b: dict[str, float],
    pass_k_criticas_b: dict[str, bool],
) -> Decisao:
    """Taxas em fração (0–1); ruído em pontos percentuais."""
    motivos = []
    delta = 100 * (taxa_b - taxa_a)
    exigido = max(FATOR_RUIDO * ruido_pp, GANHO_MINIMO_PP)
    c1 = delta >= exigido
    motivos.append(f"(1) delta médio {delta:+.1f} p.p. {'>=' if c1 else '<'} exigido {exigido:.1f} p.p.")

    tolerancia = max(ruido_pp, QUEDA_MAXIMA_CLASSE_PP)
    quedas = {c: 100 * (taxas_classe_a[c] - taxas_classe_b.get(c, 0.0)) for c in taxas_classe_a}
    piores = {c: q for c, q in quedas.items() if q > tolerancia}
    c2 = not piores
    motivos.append(
        f"(2) queda por classe tolerada até {tolerancia:.1f} p.p.: "
        + ("nenhuma classe passou do limite" if c2 else ", ".join(f"{c} caiu {q:.1f} p.p." for c, q in piores.items()))
    )

    falhas = [k for k, ok in pass_k_criticas_b.items() if not ok]
    c3 = not falhas
    motivos.append("(3) críticas pass^k: " + ("todas 100%" if c3 else f"falharam: {', '.join(falhas)}"))
    return Decisao(c1 and c2 and c3, motivos)
