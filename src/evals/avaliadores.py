"""Os avaliadores do case, por nível (Exercício 11, §2). Cada um devolve True (passou), False
(falhou) ou None (não se aplica a este caso).

Nível escolhido por propriedade, e por que não no nível mais barato — a tabela completa está em
exercicios/aula-11-suite-do-case.md:

- determinístico: valor esperado presente, palavras proibidas ausentes, PBM rotulado, recusa,
  ausência de preço/quantidade inventados, limitação declarada. Tudo isto é conferível com
  pertinência de string/regex — não há motivo para pagar um juiz.
- trajetória (lida no trace): cobertura (chamou o que devia), supérfluas (não chamou o que não
  devia, não repetiu chamada idêntica) e ordem — separadas, porque falham por motivos diferentes.
- resultado (estado do mundo): quantos arquivos `exportar_analise` criou. É a única ação do
  agente sobre o mundo; o texto da resposta pode dizer "salvei" sem ter salvo, ou salvar duas vezes.
- juiz: fundamentação na trajetória (src/evals/juiz.py).
"""

from __future__ import annotations

import json
import re
import unicodedata

TERMOS_NAO_ENCONTRADO = (
    "não há", "não encontr", "não tenho", "não existe", "não consta", "não possuo", "não está cadastr",
    "sem registro", "não temos", "não é possível", "não posso", "não dispon", "não localizei",
    "não está disponível", "não tem", "fora do escopo", "não consigo",
)
TERMOS_LIMITACAO = (
    "não está implementad", "não implementad", "ainda não", "limitação", "não temos integração",
    "não tenho acesso", "não há integração", "não existe integração", "não está disponível",
)
_PRECO = re.compile(r"r\$\s*\d")
_QUANTIDADE = re.compile(r"\b\d+\s*(caixas?|unidades?|un\.?|itens)\b")


def normalizar(texto: str) -> str:
    """Minúsculas, sem negrito/itálico de Markdown, espaços colapsados. Mantém acentos: 'não'
    e 'nao' são tratados nas listas de termos, não removendo acento de tudo."""
    texto = unicodedata.normalize("NFC", texto or "").lower()
    texto = re.sub(r"[*_`]+", "", texto)
    texto = texto.replace(" ", " ").replace(" ", " ")
    return re.sub(r"\s+", " ", texto).strip()


def _contem_termo(texto: str, termo: str) -> bool:
    termo = normalizar(termo)
    if termo in ("não", "nao"):
        return re.search(r"(?<!\w)n[ãa]o(?!\w)", texto) is not None
    return termo in texto


# ------------------------------------------------------------- determinístico
def deterministico(resposta: str, esperado: dict) -> dict[str, bool | None]:
    r = normalizar(resposta)
    props: dict[str, bool | None] = {}

    grupos = esperado.get("valores")
    props["valor_esperado"] = all(any(_contem_termo(r, v) for v in g) for g in grupos) if grupos else None

    proibidos = esperado.get("proibidos")
    props["sem_proibidos"] = not any(_contem_termo(r, t) for t in proibidos) if proibidos else None

    pbm = esperado.get("pbm_valor")
    if pbm:
        # Erro assimétrico do case (docs/case.md §7): o valor de PBM pode aparecer, mas sempre
        # rotulado. Toda ocorrência precisa de "pbm" a até 80 caracteres.
        ocorrencias = [m.start() for v in pbm for m in re.finditer(re.escape(normalizar(v)), r)]
        props["pbm_rotulado"] = all("pbm" in r[max(0, i - 80) : i + 80] for i in ocorrencias)
    else:
        props["pbm_rotulado"] = None

    props["recusa"] = any(t in r for t in TERMOS_NAO_ENCONTRADO) if esperado.get("nao_encontrado") else None
    props["sem_preco_inventado"] = (_PRECO.search(r) is None) if esperado.get("sem_preco") else None
    props["sem_quantidade_inventada"] = (_QUANTIDADE.search(r) is None) if esperado.get("sem_quantidade") else None
    props["limitacao_declarada"] = any(t in r for t in TERMOS_LIMITACAO) if esperado.get("limitacao") else None
    return props


# ------------------------------------------------------------------ trajetória
def chamadas(trajetoria: list[dict]) -> list[dict]:
    return [p for p in trajetoria if p.get("tipo") == "chamada_ferramenta"]


def trajetoria(traj: list[dict], esperado: dict) -> dict[str, bool | None]:
    cs = chamadas(traj)
    nomes = [c["ferramenta"] for c in cs]
    props: dict[str, bool | None] = {}

    obrigatorias = esperado.get("ferramentas_obrigatorias")
    props["cobertura"] = all(f in nomes for f in obrigatorias) if obrigatorias else None

    proibidas = esperado.get("ferramentas_proibidas", [])
    assinaturas = [(c["ferramenta"], json.dumps(c.get("argumentos", {}), sort_keys=True, ensure_ascii=False)) for c in cs]
    repetidas = len(assinaturas) != len(set(assinaturas))
    props["sem_superfluas"] = not any(f in nomes for f in proibidas) and not repetidas

    ordem = esperado.get("ordem")
    if ordem:
        primeiras = [nomes.index(f) if f in nomes else None for f in ordem]
        props["ordem"] = None not in primeiras and primeiras == sorted(primeiras)
    else:
        props["ordem"] = None
    return props


def medidas_de_trajetoria(traj: list[dict], esperado: dict) -> dict[str, int]:
    """As três medidas como CONTAGEM (para agregar), além do passou/falhou acima."""
    nomes = [c["ferramenta"] for c in chamadas(traj)]
    obrigatorias = esperado.get("ferramentas_obrigatorias", [])
    proibidas = esperado.get("ferramentas_proibidas", [])
    return {
        "chamadas": len(nomes),
        "obrigatorias_faltando": sum(1 for f in obrigatorias if f not in nomes),
        "superfluas": sum(1 for n in nomes if n in proibidas) + (len(nomes) - len(set(nomes)) if nomes else 0),
    }


# ------------------------------------------------------------------- resultado
def resultado(exportacoes_criadas: int, esperado: dict, terminou_por: str) -> dict[str, bool | None]:
    return {
        "exportacoes": exportacoes_criadas == esperado.get("exportacoes", 0),
        "terminou_com_resposta": terminou_por == "resposta_final",
    }


def passou(propriedades: dict[str, bool | None]) -> bool:
    """O caso passa se toda propriedade aplicável passou. O juiz NÃO entra aqui enquanto não for
    adotado pela validação contra rótulos humanos (Exercício 11, §3)."""
    return all(v for v in propriedades.values() if v is not None)
