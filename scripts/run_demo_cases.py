"""Roda os 4 casos de demonstração exigidos por docs/01-primeira-entrega.md, item 4.5,
com o modelo ATIVO (LLM_BASE_URL/LLM_MODEL, decidido em docs/modelos.md §3.4), e grava
cada trajetória em logs/.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # console Windows (cp1252) engasga em texto do modelo com acento
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()

from src.core.budget import Orcamento  # noqa: E402
from src.core.logging_utils import salvar_trajetoria  # noqa: E402
from src.projects.farmacia_precos import config  # noqa: E402
from src.projects.farmacia_precos.fabrica import montar_agente  # noqa: E402

CASOS = [
    {
        "arquivo": "caso-01-simples.json",
        "descricao": "Caso simples — deve funcionar sem ambiguidade.",
        "pergunta": "Qual o preço atual da Novalgina 500mg na farmácia Araujo?",
    },
    {
        "arquivo": "caso-02-divergencia.json",
        "descricao": "Divergência — o usuário afirma um valor que não bate com o dado real.",
        "pergunta": "Tenho certeza que a Drogasil vende a Trayenta 5mg por R$150. Por que seu relatório mostra outro valor?",
    },
    {
        "arquivo": "caso-03-registro-inexistente.json",
        "descricao": "Registro inexistente — produto e farmácia fora do cadastro.",
        "pergunta": "Qual o preço da Ivermectina 6mg na farmácia Extrafarma?",
    },
    {
        "arquivo": "caso-04-nao-deve-exportar.json",
        "descricao": "Não deve disparar a ação de escrita (exportar_analise) sem pedido explícito.",
        "pergunta": "O Ozempic 1mg está em falta em alguma farmácia? Desde quando?",
    },
]


def main() -> None:
    agente, banco, config_modelo = montar_agente()
    try:
        for caso in CASOS:
            print(f"\n=== {caso['arquivo']} — {caso['descricao']} ===")
            print(f"Pergunta: {caso['pergunta']}")
            orcamento = Orcamento(max_passos=config.max_passos(), max_tokens=config.max_tokens())
            resultado = agente.executar(caso["pergunta"], orcamento)

            ferramentas_chamadas = [
                passo["ferramenta"] for passo in resultado.trajetoria if passo["tipo"] == "chamada_ferramenta"
            ]
            print(f"Ferramentas chamadas: {ferramentas_chamadas or '(nenhuma)'}")
            print(f"Resposta final: {resultado.resposta_final}")

            if caso["arquivo"] == "caso-04-nao-deve-exportar.json":
                disparou_exportacao = "exportar_analise" in ferramentas_chamadas
                print(f"[checagem] exportar_analise foi chamada? {disparou_exportacao} (esperado: False)")

            caminho = salvar_trajetoria(
                config.PASTA_LOGS,
                caso["arquivo"],
                caso["pergunta"],
                config_modelo.modelo,
                resultado,
                metadados_extra={"fonte_dados": banco.fonte, "descricao_caso": caso["descricao"]},
            )
            print(f"Log salvo em {caminho}")
    finally:
        banco.close()


if __name__ == "__main__":
    main()
