"""O golden dataset do case (Exercício 11, §1).

`DATASET_VERSAO` sobe a cada mudança de caso (semver: patch = texto do `por_que_existe`, minor =
caso novo, major = esperado de caso existente mudou — o que invalida comparação com execuções
anteriores). O carimbo também leva o sha256 do arquivo: uma edição que esqueceu de subir a
versão aparece como hash diferente com a mesma versão.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

CAMINHO_DATASET = Path(__file__).resolve().parents[2] / "dados" / "avaliacao" / "golden_v1.jsonl"
DATASET_VERSAO = "1.0.0"
ORIGENS = ("producao", "desenvolvimento", "sintetico")


@dataclass(frozen=True)
class Caso:
    id: str
    entrada: str
    classe: str
    origem: str
    revisado_por: str
    por_que_existe: str
    esperado: dict


def carregar_dataset(caminho: Path = CAMINHO_DATASET) -> list[Caso]:
    casos = []
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        if linha.strip():
            d = json.loads(linha)
            casos.append(Caso(d["id"], d["entrada"], d["classe"], d["origem"], d["revisado_por"], d["por_que_existe"], d["esperado"]))
    validar(casos)
    return casos


def validar(casos: list[Caso]) -> None:
    ids = [c.id for c in casos]
    if len(ids) != len(set(ids)):
        raise ValueError("ids repetidos no dataset")
    for c in casos:
        if c.origem not in ORIGENS:
            raise ValueError(f"{c.id}: origem inválida {c.origem!r}")
        if not c.por_que_existe.strip():
            raise ValueError(f"{c.id}: falta por_que_existe")
        if not c.esperado:
            raise ValueError(f"{c.id}: falta esperado")


def hash_dataset(caminho: Path = CAMINHO_DATASET) -> str:
    return hashlib.sha256(caminho.read_bytes()).hexdigest()[:12]


def resumo(casos: list[Caso]) -> dict:
    return {
        "por_origem": Counter(c.origem for c in casos),
        "por_classe": Counter(c.classe for c in casos),
        "sinteticos_sem_revisao": [c.id for c in casos if c.origem == "sintetico" and c.revisado_por == "pendente"],
    }
