"""O que o sistema faz SEM os reducers (Parte 2, §7.2). Determinístico: modelo falso, sem rede.

Compila o MESMO desenho do grafo (`construir_grafo`) com dois estados alterados e roda o mesmo
roteiro de dois turnos nos três:

A. o estado do sistema (`EstadoGrafo`), com reducers — a referência;
B. `eventos` e `trajetoria` SEM reducer — os dois campos que os ramos paralelos `carregar_memoria`
   e `triagem` escrevem no MESMO superstep;
C. `mensagens` SEM reducer — o campo da conversa, escrito por `receber_entrada` e `montar_saida`
   em supersteps DIFERENTES.

Uso: python scripts/demo_reducer.py  (saída em logs/parte2/demo_reducer.txt)
"""

from __future__ import annotations

import io
import sys
import tempfile
import typing
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, TypedDict

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402

from src.core.prompts import PromptVersionado  # noqa: E402
from src.core.tools import Ferramenta, RegistroFerramentas  # noqa: E402
from src.grafo.dependencias import Dependencias, Tetos  # noqa: E402
from src.grafo.estado import EstadoGrafo  # noqa: E402
from src.grafo.execucao import executar_turno  # noqa: E402
from src.grafo.falsos import ModeloFalso, chamada, resposta, triagem_json  # noqa: E402
from src.grafo.grafo import construir_grafo  # noqa: E402

SAIDA = Path(__file__).resolve().parents[1] / "logs" / "parte2" / "demo_reducer.txt"


def estado_sem_reducer(*campos: str) -> type:
    """Cópia de EstadoGrafo em que `campos` perdem o reducer (viram LastValue, o padrão)."""
    dicas = typing.get_type_hints(EstadoGrafo, include_extras=True)
    novas: dict[str, Any] = {}
    for nome, tipo in dicas.items():
        novas[nome] = typing.get_args(tipo)[0] if nome in campos else tipo
    return TypedDict(f"EstadoSem_{'_'.join(campos)}", novas, total=False)


def deps_falsas() -> Dependencias:
    registro = RegistroFerramentas()
    registro.registrar(Ferramenta(
        "consultar_precos", "preços", {"type": "object"},
        lambda produto, farmacia="", modo="atual": {"encontrado": True, "fonte": "falsa",
                                                    "resultados": [{"Produto": produto, "PrecoFarmacia": 10.0, "DataUltimaColeta": "2026-09-19"}]},
        "leitura", True, "falso"))
    modelo = ModeloFalso(
        triagens=[triagem_json(), triagem_json()],
        passos=[resposta(tool_calls=[chamada("consultar_precos", {"produto": "A"})]), resposta("A custa R$ 10,00."),
                resposta(tool_calls=[chamada("consultar_precos", {"produto": "B"})]), resposta("B custa R$ 10,00.")],
    )
    p = PromptVersionado("demo", "v0", "prompt", None)
    return Dependencias(cliente=modelo, modelo="falso", ferramentas=registro, prompt_agente=p, prompt_triagem=p,
                        tetos=Tetos(max_segundos=10_000))


def rodar(nome: str, estado_cls: type) -> None:
    print(f"\n### {nome}")
    grafo = construir_grafo(estado_cls).compile(checkpointer=InMemorySaver())
    deps = deps_falsas()
    with tempfile.TemporaryDirectory() as tmp:
        for texto in ("preço de A?", "e de B?"):
            try:
                r = executar_turno(texto, deps, "G-DEMO", "s1", grafo=grafo, pasta_logs=Path(tmp))
            except Exception as exc:  # noqa: BLE001 — a demonstração é justamente o erro
                print(f"  turno '{texto}': EXCEÇÃO {type(exc).__name__}: {str(exc).splitlines()[0]}")
                return
            est = r.estado
            nos_eventos = [e["no"] for e in est.get("eventos", [])]
            print(f"  turno '{texto}': saída = {r.saida.resultado!r} ({r.saida.suficiencia})")
            print(f"    eventos registrados ({len(nos_eventos)}): {nos_eventos}")
            print(f"    trajetória: {[p.get('tipo') for p in est.get('trajetoria', [])]}")
            print(f"    conversa no checkpoint: {[m['texto'] for m in est.get('mensagens', [])]}")
            print(f"    o modelo viu de histórico: {[m['content'] for m in deps.cliente.recebidas[-1] if m['role'] in ('user', 'assistant') and m.get('content')]}")


def main() -> None:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        print("Demonstração dos reducers — mesmo grafo, mesmo roteiro de 2 turnos, modelo falso.")
        rodar("A. estado do sistema (com reducers)", EstadoGrafo)
        rodar("B. eventos e trajetoria SEM reducer (escritos em paralelo)", estado_sem_reducer("eventos", "trajetoria"))
        rodar("C. mensagens SEM reducer (escrito em supersteps diferentes)", estado_sem_reducer("mensagens"))
    texto = buffer.getvalue()
    print(texto)
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    SAIDA.write_text(texto, encoding="utf-8")


if __name__ == "__main__":
    main()
