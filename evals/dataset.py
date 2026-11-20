"""O golden dataset da Parte 3 (§1.1): `evals/dataset/golden_v2.jsonl`.

v2.0.0 = os 24 casos do v1 (Exercício 11) + os casos demonstrados da Parte 2 que faltavam (coleta
antiga, aprovação repetida, conversa em dois turnos, ambígua, fora do corpus) + 4 de segurança.
Versionamento: patch = texto de `por_que_existe`; minor = caso novo; major = esperado de caso
existente mudou (invalida comparação com rodadas anteriores). O carimbo leva também o sha256 do
arquivo, para uma edição que esqueceu de subir a versão aparecer.

Campos de `esperado` além dos do v1 (src/evals/avaliadores.py):

| campo | o que pede |
|---|---|
| `turnos` (no caso) | lista de `{texto, sessao}`; sem ele, um turno com `entrada` |
| `aprovacoes` | decisões entregues, em ordem, a cada pausa; pausa sem decisão restante = fica pendente |
| `repetir_aprovacao` | reentrega a última decisão a partir do checkpoint da pausa (§8.5 da Parte 2) |
| `data_referencia` | `AGENT_DATA_REFERENCIA` deste caso (padrão da suíte: 2026-09-20, a data do espelho) |
| `suficiencia`, `suficiencia_por_turno`, `motivo` | o contrato de saída (§1.2 da Parte 2) |
| `aprovacao_fundamentada` | todo valor em `dados_resumo` de um pedido de aprovação aparece no resultado de alguma ferramenta |
| `max_exportacoes` | teto de arquivos criados |
| `dado_pessoal_ausente` | strings que não podem aparecer no que foi enviado ao modelo, no trace, no checkpoint nem na memória |
| `texto_injetado_ausente_da_memoria` | strings que não podem chegar ao contexto de memória do último turno nem ao banco da memória |
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

CAMINHO = Path(__file__).resolve().parent / "dataset" / "golden_v2.jsonl"
VERSAO = "2.0.0"
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
    turnos: list = field(default_factory=list)

    @property
    def turnos_ou_entrada(self) -> list[dict]:
        return self.turnos or [{"texto": self.entrada, "sessao": "a"}]


def carregar(caminho: Path = CAMINHO) -> list[Caso]:
    casos = []
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        if linha.strip():
            d = json.loads(linha)
            casos.append(Caso(d["id"], d["entrada"], d["classe"], d["origem"], d["revisado_por"], d["por_que_existe"],
                              d["esperado"], d.get("turnos", [])))
    validar(casos)
    return casos


def validar(casos: list[Caso]) -> None:
    ids = [c.id for c in casos]
    if len(ids) != len(set(ids)):
        raise ValueError("ids repetidos no dataset")
    for c in casos:
        if c.origem not in ORIGENS:
            raise ValueError(f"{c.id}: origem inválida {c.origem!r}")
        if not c.por_que_existe.strip() or not c.esperado:
            raise ValueError(f"{c.id}: falta por_que_existe ou esperado")
        if not c.revisado_por.strip():
            raise ValueError(f"{c.id}: revisado_por vazio — declare o revisor ou 'pendente'")
    classes = Counter(c.classe for c in casos)
    if len(classes) < 3 or min(classes.values()) < 2:
        raise ValueError(f"composição: precisa de ≥3 classes com ≥2 casos cada ({dict(classes)})")


def hash_arquivo(caminho: Path = CAMINHO) -> str:
    return hashlib.sha256(caminho.read_bytes()).hexdigest()[:12]


def resumo(casos: list[Caso]) -> dict:
    return {"n": len(casos), "por_origem": dict(Counter(c.origem for c in casos)), "por_classe": dict(Counter(c.classe for c in casos)),
            "revisao_pendente": [c.id for c in casos if c.revisado_por.startswith("pendente")]}
