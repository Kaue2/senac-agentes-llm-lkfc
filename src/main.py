"""CLI do agente — Parte 1: um único projeto (farmacia_precos).

Uso: python -m src.main "sua pergunta"

Um projeto futuro (outro contexto/banco/ferramentas, ver docs/case.md sobre o núcleo
genérico) adicionaria seu próprio src/projects/<nome>/fabrica.py e este arquivo passaria
a escolher qual montar; por ora, com um único projeto, chama direto.
"""

from __future__ import annotations

import sys
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")  # console Windows (cp1252) engasga em texto do modelo com acento

from dotenv import load_dotenv

load_dotenv()

from src.core.budget import Orcamento  # noqa: E402  (import após load_dotenv de propósito)
from src.core.logging_utils import salvar_trajetoria  # noqa: E402
from src.projects.farmacia_precos import config  # noqa: E402
from src.projects.farmacia_precos.fabrica import montar_agente  # noqa: E402


def main() -> None:
    if len(sys.argv) < 2:
        print('Uso: python -m src.main "sua pergunta"')
        raise SystemExit(1)
    pergunta = " ".join(sys.argv[1:])

    try:
        agente, banco, config_modelo = montar_agente()
    except RuntimeError as exc:
        print(f"Configuração incompleta: {exc}")
        print("Copie .env.example para .env e preencha as variáveis indicadas.")
        raise SystemExit(1)

    try:
        orcamento = Orcamento(max_passos=config.max_passos(), max_tokens=config.max_tokens())
        resultado = agente.executar(pergunta, orcamento)

        print(f"[fonte de dados: {banco.fonte}]")
        if resultado.resposta_final:
            print(resultado.resposta_final)
        else:
            print(f"(sem resposta final — terminou por: {resultado.motivo_terminacao})")

        nome_arquivo = f"execucao_{datetime.now().strftime('%Y%m%dT%H%M%S')}.json"
        caminho = salvar_trajetoria(
            config.PASTA_LOGS,
            nome_arquivo,
            pergunta,
            config_modelo.modelo,
            resultado,
            metadados_extra={"fonte_dados": banco.fonte},
        )
        print(f"[log salvo em {caminho}]")
    finally:
        banco.close()


if __name__ == "__main__":
    main()
