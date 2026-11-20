"""As 4 ferramentas do agente de BI de farmácia (docs/case.md §2.4).

`consultar_precos` é a integração real do item 4.2 (fala com o banco de preços do
fractal-precos, ou seu espelho — ver db.py). `consultar_vendas` e `consultar_estoque`
são placeholders: os outros dois pilares do case (vendas, estoque) ainda não têm
função de captura nem schema — isso é trabalho futuro do time (docs/case.md §2.11).
Eles ficam registrados desde já para que o modelo saiba que essas perguntas existem e
para que o time só precise substituir o corpo da função quando a captura estiver
pronta, sem mexer no agente. `exportar_analise` é a única ferramenta de escrita: grava
o relatório da pergunta atual em disco, não em nenhum dado de negócio (ver docs/case.md
§2.4 sobre por que isso não contradiz o sistema ser "somente leitura" sobre preço/venda/
estoque).
"""

from __future__ import annotations

import hashlib
import os
from datetime import date, datetime, timezone
from pathlib import Path

from src.core.tools import Ferramenta, RegistroFerramentas

from .db import BancoPrecos

PASTA_RAIZ = Path(__file__).resolve().parents[3]
PASTA_EXPORTS = PASTA_RAIZ / "dados" / "exports"


def _consultar_precos(banco: BancoPrecos, produto: str, modo: str = "atual", farmacia: str = "", dias_historico: int = 30) -> dict:
    farmacia_ou_none = farmacia or None
    if modo == "historico":
        linhas = banco.historico_precos(produto, farmacia_ou_none, dias_historico)
    elif modo == "ruptura":
        linhas = banco.status_ruptura(produto, farmacia_ou_none)
    else:
        linhas = banco.preco_atual(produto, farmacia_ou_none)

    if not linhas:
        return {
            "encontrado": False,
            "fonte": banco.fonte,
            "mensagem": (
                f"Nenhum registro para produto='{produto}'"
                + (f", farmacia='{farmacia}'" if farmacia else "")
                + " no banco de preços. Pode ser um produto/farmácia fora do cadastro — "
                "não invente um preço, informe ao usuário que não há esse dado."
            ),
        }
    hoje = data_referencia()
    for linha in linhas:
        linha.update(situacao_da_linha(linha, modo, hoje))
    return {"encontrado": True, "fonte": banco.fonte, "data_referencia": hoje.isoformat(), "resultados": linhas}


DIAS_COLETA_RECENTE = 3          # regras-ruptura#s04: mais de 3 dias sem coleta = "sem coleta recente"
COLETAS_RUPTURA_CONFIRMADA = 2   # regras-ruptura#s03: 2 coletas seguidas indisponível = confirmada


def data_referencia() -> date:
    """O "hoje" das regras de domínio que dependem de data. Em produção é a data corrente; a suíte
    de avaliação fixa `AGENT_DATA_REFERENCIA` (AAAA-MM-DD) porque o espelho sintético parou numa
    data — sem isso, toda pergunta de ruptura viraria "sem coleta recente" com o passar dos dias,
    e os casos do golden mudariam de resposta sem nenhuma mudança no sistema."""
    fixa = os.environ.get("AGENT_DATA_REFERENCIA", "").strip()
    return date.fromisoformat(fixa) if fixa else date.today()


def situacao_da_linha(linha: dict, modo: str, hoje: date) -> dict:
    """As regras de ruptura do corpus (regras-ruptura#s02–s04), aplicadas em CÓDIGO na linha que o
    banco devolveu. Correção da Parte 2 (docs/mudancas.md): o agente só seguia a regra se decidisse
    consultar a base de conhecimento — e no caso 4 não consultou."""
    bruto = linha.get("DataUltimaColeta") or linha.get("UltimaColeta") or linha.get("DataHoraColeta")
    if not bruto:
        return {}
    ultima = datetime.fromisoformat(str(bruto)[:19]).date()
    dias = (hoje - ultima).days
    situacao: dict = {"dias_desde_ultima_coleta": dias}
    if dias > DIAS_COLETA_RECENTE:
        situacao["situacao_coleta"] = "sem_coleta_recente"
        situacao["aviso"] = (
            f"Última coleta há {dias} dias (mais de {DIAS_COLETA_RECENTE}): pela regra da rede não se afirma "
            "nada sobre disponibilidade atual; informe a data da última coleta."
        )
        return situacao
    situacao["situacao_coleta"] = "recente"
    if modo == "ruptura" and "Disponivel" in linha:
        if linha["Disponivel"]:
            situacao["situacao_ruptura"] = "disponivel"
        elif int(linha.get("QtdColetasNesseEstado") or 0) >= COLETAS_RUPTURA_CONFIRMADA:
            situacao["situacao_ruptura"] = "ruptura_confirmada"
        else:
            situacao["situacao_ruptura"] = "ruptura_a_confirmar"
    return situacao


def _consultar_vendas(produto: str = "", farmacia: str = "", periodo: str = "") -> dict:
    return {
        "status": "nao_implementado",
        "pilar": "vendas",
        "mensagem": (
            "A captura de dados de vendas ainda não existe — a função e o schema serão "
            "desenvolvidos pela equipe depois (ver docs/case.md §2.10/§2.11). Explique essa "
            "limitação ao usuário em vez de estimar ou inventar um número de vendas."
        ),
    }


def _consultar_estoque(produto: str = "", farmacia: str = "") -> dict:
    return {
        "status": "nao_implementado",
        "pilar": "estoque",
        "mensagem": (
            "A captura de dados de estoque ainda não existe — a função e o schema serão "
            "desenvolvidos pela equipe depois (ver docs/case.md §2.10/§2.11). Explique essa "
            "limitação ao usuário em vez de estimar ou inventar um nível de estoque."
        ),
    }


def chave_exportacao(pergunta: str, dados_resumo: str, explicacao: str) -> str:
    """Chave de idempotência derivada do CONTEÚDO (Parte 2, §8.5): o mesmo conteúdo dá a mesma
    chave, e a segunda aprovação do mesmo pedido encontra o arquivo da primeira. Na Parte 1 o
    arquivo era nomeado pelo horário, e uma retentativa gerava um segundo arquivo (docs/memoria.md
    §1.1, "falha conhecida")."""
    normalizado = "\x1f".join(" ".join(t.split()) for t in (pergunta, dados_resumo, explicacao))
    return hashlib.sha256(normalizado.encode("utf-8")).hexdigest()[:16]


def _exportar_analise(pergunta: str, dados_resumo: str, explicacao: str, pasta: Path | None = None) -> dict:
    pasta = pasta or PASTA_EXPORTS
    pasta.mkdir(parents=True, exist_ok=True)
    chave = chave_exportacao(pergunta, dados_resumo, explicacao)
    caminho = pasta / f"analise_{chave}.md"
    arquivo = str(caminho.relative_to(PASTA_RAIZ)) if caminho.is_relative_to(PASTA_RAIZ) else str(caminho)
    if caminho.exists():
        return {"status": "ok", "arquivo": arquivo, "chave_idempotencia": chave, "ja_existia": True}
    agora = datetime.now(timezone.utc)
    conteudo = (
        f"# Análise exportada — {agora.isoformat(timespec='seconds')}\n\n"
        f"Chave de idempotência: `{chave}`\n\n"
        f"## Pergunta\n{pergunta}\n\n"
        f"## Dados\n{dados_resumo}\n\n"
        f"## Explicação\n{explicacao}\n"
    )
    # "x": cria só se não existir — duas aprovações simultâneas não sobrescrevem uma à outra.
    try:
        with caminho.open("x", encoding="utf-8") as f:
            f.write(conteudo)
    except FileExistsError:
        return {"status": "ok", "arquivo": arquivo, "chave_idempotencia": chave, "ja_existia": True}
    return {"status": "ok", "arquivo": arquivo, "chave_idempotencia": chave, "ja_existia": False}


def registrar_ferramentas_farmacia(registro: RegistroFerramentas, banco: BancoPrecos, pasta_exports: Path | None = None) -> None:
    registro.registrar(
        Ferramenta(
            nome="consultar_precos",
            descricao=(
                "Consulta o banco de preços de farmácias (fractal-precos). modo='atual' retorna o "
                "preço mais recente (tabela, farmácia, PBM se houver programa); modo='historico' "
                "retorna a série de coletas dos últimos N dias; modo='ruptura' retorna desde quando "
                "o produto está disponível ou indisponível em cada farmácia. Não inclui vendas nem "
                "estoque — use as outras ferramentas para isso."
            ),
            parametros_json_schema={
                "type": "object",
                "properties": {
                    "produto": {"type": "string", "description": "Nome ou parte do nome do produto."},
                    "farmacia": {"type": "string", "description": "Nome da farmácia. Omita para todas."},
                    "modo": {
                        "type": "string",
                        "enum": ["atual", "historico", "ruptura"],
                        "description": "atual (padrão), historico ou ruptura.",
                    },
                    "dias_historico": {
                        "type": "integer",
                        "description": "Só usado com modo='historico'. Padrão 30.",
                    },
                },
                "required": ["produto"],
            },
            handler=lambda **kwargs: _consultar_precos(banco, **kwargs),
            leitura_ou_escrita="leitura",
            reversivel=True,
            conversa_com="Banco de preços fractal-precos (SQL Server real, ou espelho SQLite local)",
        )
    )
    registro.registrar(
        Ferramenta(
            nome="consultar_vendas",
            descricao="Consulta volume/receita de vendas por produto/farmácia/período. AINDA NÃO IMPLEMENTADA.",
            parametros_json_schema={
                "type": "object",
                "properties": {
                    "produto": {"type": "string"},
                    "farmacia": {"type": "string"},
                    "periodo": {"type": "string", "description": "Ex.: 'último mês', '2026-08'."},
                },
                "required": [],
            },
            handler=_consultar_vendas,
            leitura_ou_escrita="leitura",
            reversivel=True,
            conversa_com="Sistema de vendas interno (ainda não existe — trabalho futuro do time)",
        )
    )
    registro.registrar(
        Ferramenta(
            nome="consultar_estoque",
            descricao="Consulta nível de estoque por produto/farmácia. AINDA NÃO IMPLEMENTADA.",
            parametros_json_schema={
                "type": "object",
                "properties": {
                    "produto": {"type": "string"},
                    "farmacia": {"type": "string"},
                },
                "required": [],
            },
            handler=_consultar_estoque,
            leitura_ou_escrita="leitura",
            reversivel=True,
            conversa_com="Sistema de estoque interno (ainda não existe — trabalho futuro do time)",
        )
    )
    registro.registrar(
        Ferramenta(
            nome="exportar_analise",
            descricao=(
                "Salva a pergunta atual, os dados usados e a explicação num arquivo .md local, "
                "para o gestor guardar/compartilhar. Só chame quando o usuário pedir para salvar, "
                "exportar ou guardar a análise — não chame por conta própria."
            ),
            parametros_json_schema={
                "type": "object",
                "properties": {
                    "pergunta": {"type": "string"},
                    "dados_resumo": {"type": "string", "description": "Os dados numéricos usados na resposta."},
                    "explicacao": {"type": "string", "description": "A explicação dada ao usuário."},
                },
                "required": ["pergunta", "dados_resumo", "explicacao"],
            },
            handler=lambda pergunta, dados_resumo, explicacao: _exportar_analise(pergunta, dados_resumo, explicacao, pasta_exports),
            leitura_ou_escrita="escrita",
            reversivel=True,
            conversa_com="Sistema de arquivos local (dados/exports/) — nunca dados de negócio",
        )
    )
