"""Medidores do buscador (Aula 06): conjunto de perguntas, recall@k e calibração do portão.

Critério de acerto de recuperação: a pergunta conta como recuperada se ALGUM dos k primeiros
trechos contém, por inteiro, ALGUMA das evidências rotuladas para ela (comparação com espaços
normalizados). Exigir a evidência inteira é deliberado: um corte que partiu a frase da exceção
ao meio entregou ao modelo metade da regra, e isso precisa contar como falha do chunking.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .chunking import Trecho
from .corpus import normalizar_espacos
from .indice import Resultado

CAMINHO_PERGUNTAS = Path(__file__).resolve().parents[2] / "dados" / "avaliacao" / "perguntas_rag_v1.jsonl"


@dataclass(frozen=True)
class Pergunta:
    id: str
    pergunta: str
    tem_resposta: bool
    tipo: str
    doc_id: str | None
    evidencias: tuple[str, ...]
    por_que_existe: str = field(default="", compare=False)
    resposta_referencia: str | None = field(default=None, compare=False)


def carregar_perguntas(caminho: Path = CAMINHO_PERGUNTAS) -> list[Pergunta]:
    perguntas = []
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        if not linha.strip():
            continue
        d = json.loads(linha)
        perguntas.append(
            Pergunta(
                id=d["id"],
                pergunta=d["pergunta"],
                tem_resposta=d["tem_resposta"],
                tipo=d["tipo"],
                doc_id=d["doc_id"],
                evidencias=tuple(d["evidencias"]),
                por_que_existe=d.get("por_que_existe", ""),
                resposta_referencia=d.get("resposta_referencia"),
            )
        )
    if len({p.id for p in perguntas}) != len(perguntas):
        raise ValueError("ids de pergunta repetidos")
    return perguntas


def trecho_contem_evidencia(trecho: Trecho, pergunta: Pergunta) -> bool:
    texto = normalizar_espacos(trecho.texto)
    return any(normalizar_espacos(e) in texto for e in pergunta.evidencias)


def posicao_da_evidencia(resultados: list[Resultado], pergunta: Pergunta) -> int | None:
    """Posição (1-based) do primeiro trecho que contém a evidência, ou None."""
    for r in resultados:
        if trecho_contem_evidencia(r.trecho, pergunta):
            return r.posicao
    return None


def evidencia_intacta_no_indice(trechos: list[Trecho], pergunta: Pergunta) -> bool:
    """A evidência existe inteira em algum trecho do índice? Se não existe, nenhum k e nenhum
    modelo de embedding conseguem recuperá-la — o defeito é do chunking, por construção."""
    return any(trecho_contem_evidencia(t, pergunta) for t in trechos)


def recall_at_k(posicoes: dict[str, int | None], k: int) -> float:
    """Fração das perguntas (com resposta) cuja evidência está entre os k primeiros."""
    if not posicoes:
        return 0.0
    return sum(1 for p in posicoes.values() if p is not None and p <= k) / len(posicoes)


@dataclass(frozen=True)
class PontoDoPortao:
    limiar: float
    barradas_sem_resposta: int
    total_sem_resposta: int
    barradas_com_resposta: int
    total_com_resposta: int


def varrer_limiares(
    menor_distancia: dict[str, float], perguntas: list[Pergunta], limiares: list[float]
) -> list[PontoDoPortao]:
    """O portão barra a pergunta quando a distância do trecho MAIS PRÓXIMO passa do limiar.
    Para cada limiar, conta as barradas de cada lado — a curva dos dois erros (Aula 07)."""
    com = [p for p in perguntas if p.tem_resposta]
    sem = [p for p in perguntas if not p.tem_resposta]
    pontos = []
    for limiar in limiares:
        pontos.append(
            PontoDoPortao(
                limiar=limiar,
                barradas_sem_resposta=sum(1 for p in sem if menor_distancia[p.id] > limiar),
                total_sem_resposta=len(sem),
                barradas_com_resposta=sum(1 for p in com if menor_distancia[p.id] > limiar),
                total_com_resposta=len(com),
            )
        )
    return pontos


def escolher_limiar(pontos: list[PontoDoPortao]) -> PontoDoPortao | None:
    """Regra de escolha, decidida antes de medir: entre os limiares que NÃO barram nenhuma
    pergunta com resposta (falso negativo zero — o enunciado da Aula 06 exige), o que barra mais
    perguntas sem resposta; em empate, o MAIOR limiar (mais folga para perguntas reais
    formuladas de outro jeito). None se nenhum limiar separa os dois lados."""
    validos = [p for p in pontos if p.barradas_com_resposta == 0]
    if not validos:
        return None
    melhor = max(p.barradas_sem_resposta for p in validos)
    return max((p for p in validos if p.barradas_sem_resposta == melhor), key=lambda p: p.limiar)
