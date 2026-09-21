"""Roda os 5 casos de domínio (docs/01-primeira-entrega.md, item 3.3) nos três
candidatos (Groq/Gemini/OpenRouter — GROQ_*/GOOGLE_*/OPENROUTER_* no .env) e grava o
resultado bruto em logs/comparacao_modelos.json.

Não inventa saída: se um candidato falhar (chave ausente, rate limit, modelo sem tool
calling, etc.), o erro fica registrado como aconteceu — vira dado para docs/modelos.md,
não é substituído por um resultado fictício.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # console Windows (cp1252) engasga em texto do modelo com acento
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()

from src.core.budget import Orcamento  # noqa: E402
from src.core.llm_client import ConfiguracaoModelo  # noqa: E402
from src.projects.farmacia_precos import config  # noqa: E402
from src.projects.farmacia_precos.db import BancoPrecos  # noqa: E402
from src.projects.farmacia_precos.fabrica import montar_agente_com_config  # noqa: E402

CANDIDATOS = ["GROQ", "GOOGLE", "OPENROUTER"]

PERGUNTAS = [
    "Qual o preço atual da Trayenta 5mg na farmácia Araujo?",
    "Tenho certeza que a Drogasil vende a Trayenta 5mg por R$150. Por que seu relatório mostra outro valor?",
    "Qual o preço da Ivermectina 6mg na farmácia Extrafarma?",
    "Como estão as vendas da Novalgina 500mg no último mês?",
    "O Ozempic 1mg está em falta em alguma farmácia? Desde quando?",
]


def main() -> None:
    banco = BancoPrecos()
    resultados: dict[str, list[dict]] = {}

    try:
        for prefixo in CANDIDATOS:
            print(f"\n### Candidato: {prefixo} ###")
            try:
                config_modelo = ConfiguracaoModelo.do_ambiente(prefixo)
            except RuntimeError as exc:
                print(f"  pulado — {exc}")
                resultados[prefixo] = [{"erro": str(exc)}]
                continue

            agente, _ = montar_agente_com_config(config_modelo, banco=banco)
            resultados[prefixo] = []
            for pergunta in PERGUNTAS:
                print(f"  - {pergunta}")
                orcamento = Orcamento(max_passos=config.max_passos(), max_tokens=config.max_tokens())
                try:
                    resultado = agente.executar(pergunta, orcamento)
                    resultados[prefixo].append(
                        {
                            "pergunta": pergunta,
                            "modelo": config_modelo.modelo,
                            "resposta_final": resultado.resposta_final,
                            "motivo_terminacao": resultado.motivo_terminacao,
                            "passos": resultado.orcamento.passos_usados,
                            "tokens": resultado.orcamento.tokens_usados,
                            "ferramentas_chamadas": [
                                p["ferramenta"] for p in resultado.trajetoria if p["tipo"] == "chamada_ferramenta"
                            ],
                        }
                    )
                except Exception as exc:  # provedor pode falhar de formas imprevisíveis (rate limit, 5xx, etc.)
                    print(f"    ERRO: {exc}")
                    resultados[prefixo].append({"pergunta": pergunta, "erro": str(exc)})
    finally:
        banco.close()

    caminho_saida = config.PASTA_LOGS / "comparacao_modelos.json"
    caminho_saida.parent.mkdir(parents=True, exist_ok=True)
    caminho_saida.write_text(json.dumps(resultados, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nResultado bruto salvo em {caminho_saida}")


if __name__ == "__main__":
    main()
