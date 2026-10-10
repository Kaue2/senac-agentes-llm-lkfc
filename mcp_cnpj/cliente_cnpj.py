"""Cliente MCP de CNPJ -> CEP (Exercício 10) — onde fica a matriz da rede concorrente.

Recebe um CNPJ pela linha de comando, abre uma sessão MCP com o servidor
`mcp_cnpj/servidor.py` (que precisa estar rodando em outro terminal), e encadeia:

    1. consultar_cnpj(cnpj) -> razão social e CEP da empresa
    2. consultar_cep(cep)   -> endereço e coordenadas (o endereço impresso sai DAQUI)

Uso:
    .venv/bin/python mcp_cnpj/cliente_cnpj.py 61.585.865/0001-51
    # servidor em outro endereço: MCP_CNPJ_URL=http://host:porta/mcp

Códigos de saída: 0 sucesso; 1 erro de domínio devolvido pelo servidor (CNPJ/CEP
inválido ou inexistente); 2 falha de infraestrutura (BrasilAPI fora, timeout);
3 servidor inacessível ou sem as ferramentas esperadas; 64 uso incorreto.

-----------------------------------------------------------------------------------
QUESTÃO DO INÍCIO: o cliente conhece a BrasilAPI?
-----------------------------------------------------------------------------------
Não. Este arquivo não tem URL, endpoint, nome de campo nem código de status da
BrasilAPI. Ele conhece apenas o CONTRATO publicado pelo servidor MCP: o endereço do
servidor, os nomes das ferramentas (`consultar_cnpj`, `consultar_cep`), o nome dos
argumentos, os campos do resultado (`razao_social`, `cep`, `street`, `neighborhood`,
`city`, `state`, `latitude`, `longitude`), a convenção de erro de domínio (campo
`erro`) e o recurso `referencia://ufs`.

Se o servidor trocasse a BrasilAPI por outra fonte (ViaCEP, a API da Receita, uma
base interna), NADA precisaria mudar aqui, desde que o servidor mantivesse esse
contrato — o trabalho de traduzir a nova fonte para os mesmos campos é dele. O
cliente só muda se o CONTRATO mudar: ferramenta renomeada, argumento renomeado,
campo do resultado removido ou renomeado (ex.: `street` virar `logradouro`), ou a
convenção de erro alterada. E é justamente esse o risco descrito na aula: essa
mudança pode chegar sem aviso, com resposta sintaticamente válida, e o sintoma aqui
seria um campo vazio impresso — não uma exceção. A defesa é fixar a versão do
servidor consumido e tratar o contrato como interface pública.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from typing import Any

from mcp import ClientSession, MCPError
from mcp.client.streamable_http import streamable_http_client

URL_SERVIDOR = os.environ.get("MCP_CNPJ_URL", "http://127.0.0.1:8000/mcp")

FERRAMENTAS_NECESSARIAS = ("consultar_cnpj", "consultar_cep")
URI_UFS = "referencia://ufs"

# Tempo máximo de espera por UMA chamada de ferramenta. Maior que o timeout HTTP do
# servidor (10s de leitura + 5s de conexão), para que, quando a fonte externa estiver
# lenta, quem desista primeiro seja o servidor — que devolve uma falha classificada —
# e não o cliente, que só saberia que "demorou".
TIMEOUT_CHAMADA_S = 30.0

SAIDA_OK, SAIDA_ERRO_DOMINIO, SAIDA_FALHA_INFRA, SAIDA_SERVIDOR, SAIDA_USO = 0, 1, 2, 3, 64


class FalhaFerramenta(Exception):
    """Falha de infraestrutura reportada pelo servidor (`isError=true` na chamada)."""


# --------------------------------------------------------------------------------
# Funções puras de formatação (sem rede) — testadas em tests/test_mcp_cnpj.py
# --------------------------------------------------------------------------------


def somente_digitos(valor: str) -> str:
    """Remove a pontuação. Entre cliente e servidor circulam só dígitos.

    Não valida: decidir se o CNPJ é válido é papel do servidor, que devolve o erro de
    domínio explicando o formato certo. Duplicar a validação aqui faria o cliente
    divergir do servidor quando a regra mudasse.
    """
    return re.sub(r"\D", "", valor or "")


def formatar_cnpj(digitos: str) -> str:
    """'19131243000197' -> '19.131.243/0001-97'. Fora de 14 dígitos, devolve como veio."""
    if len(digitos) != 14 or not digitos.isdigit():
        return digitos
    return f"{digitos[:2]}.{digitos[2:5]}.{digitos[5:8]}/{digitos[8:12]}-{digitos[12:]}"


def formatar_cep(digitos: str) -> str:
    """'01311902' -> '01311-902'. Fora de 8 dígitos, devolve como veio."""
    if len(digitos) != 8 or not digitos.isdigit():
        return digitos
    return f"{digitos[:5]}-{digitos[5:]}"


def rotulo(nome: str) -> str:
    """Rótulo com preenchimento de pontos até a coluna 18: 'CEP' -> 'CEP ............. '."""
    return f"{nome} ".ljust(17, ".") + " "


def formatar_uf(sigla: str, ufs: dict[str, str] | None) -> str:
    """'SP' -> 'São Paulo (SP)' usando o recurso de UFs; sem o recurso, só a sigla."""
    nome = (ufs or {}).get(sigla)
    return f"{nome} ({sigla})" if nome else sigla


def formatar_endereco(cep: dict[str, Any]) -> str:
    """Endereço a partir da resposta de consultar_cep: 'Rua — Bairro, Cidade/UF'.

    Partes ausentes são omitidas em vez de deixar separador solto (CEPs genéricos de
    cidade pequena vêm sem rua e sem bairro).
    """
    rua = cep.get("street") or ""
    bairro = cep.get("neighborhood") or ""
    cidade_uf = "/".join(p for p in (cep.get("city") or "", cep.get("state") or "") if p)
    local = ", ".join(p for p in (bairro, cidade_uf) if p)
    if rua and local:
        return f"{rua} — {local}"
    return rua or local or "não disponível para este CEP"


def formatar_coordenadas(cep: dict[str, Any]) -> str:
    """'-23.5475 / -46.63611', ou a mensagem fixa quando o CEP não tem coordenadas."""
    lat, lon = cep.get("latitude"), cep.get("longitude")
    if lat in (None, "") or lon in (None, ""):
        return "não disponível para este CEP"
    return f"{lat} / {lon}"


def faltando(ferramentas_disponiveis: list[str]) -> list[str]:
    """Ferramentas necessárias que o servidor não publica."""
    return [f for f in FERRAMENTAS_NECESSARIAS if f not in ferramentas_disponiveis]


def linhas_cabecalho(nome_servidor: str, ferramentas: list[str]) -> list[str]:
    return [f"SERVIDOR: {nome_servidor}   (ferramentas: {', '.join(ferramentas)})", ""]


def linhas_erro_dominio(rotulo_doc: str, valor_impresso: str, erro: dict[str, Any]) -> list[str]:
    """Mostra o erro de domínio EXATAMENTE como o servidor o devolveu — e nenhuma linha de endereço."""
    return [
        rotulo(rotulo_doc) + valor_impresso,
        rotulo("Erro") + str(erro.get("erro", "")),
        rotulo("Esperado") + str(erro.get("formato_esperado", "")),
        rotulo("O que fazer") + str(erro.get("o_que_fazer", "")),
    ]


def linhas_resultado(empresa: dict[str, Any], cep: dict[str, Any], ufs: dict[str, str] | None) -> list[str]:
    """O bloco de saída do caso de sucesso, no formato pedido pelo enunciado.

    A linha 'UF' é o acréscimo do desafio B (nome por extenso vindo do recurso); ela só
    aparece quando o recurso foi lido, para não imprimir uma linha redundante com a sigla.
    """
    linhas = [
        rotulo("CNPJ") + formatar_cnpj(empresa.get("cnpj", "")),
        rotulo("Razão social") + str(empresa.get("razao_social", "")),
        rotulo("CEP") + formatar_cep(cep.get("cep", "")),
        rotulo("Endereço") + formatar_endereco(cep),
    ]
    if ufs and cep.get("state") in ufs:
        linhas.append(rotulo("UF") + formatar_uf(cep["state"], ufs))
    linhas.append(rotulo("Lat / Long") + formatar_coordenadas(cep))
    return linhas


def interpretar_resultado(resultado: Any) -> dict[str, Any]:
    """Extrai o dicionário de um CallToolResult; `isError` vira FalhaFerramenta.

    Erro de domínio NÃO é exceção: vem como resultado normal com o campo `erro`, e é
    o chamador quem decide parar o encadeamento. Já `isError=true` é a falha de
    infraestrutura classificada pelo servidor, e sobe como exceção.
    """
    texto = " ".join(getattr(c, "text", "") for c in (resultado.content or []))
    if resultado.is_error:
        raise FalhaFerramenta(texto or "o servidor reportou falha sem mensagem")
    if isinstance(resultado.structured_content, dict):
        return resultado.structured_content
    try:
        dados = json.loads(texto)
    except ValueError as exc:
        raise FalhaFerramenta(f"resposta da ferramenta não é JSON: {texto[:200]!r}") from exc
    if not isinstance(dados, dict):
        raise FalhaFerramenta(f"resposta da ferramenta não é um objeto JSON: {texto[:200]!r}")
    return dados


# --------------------------------------------------------------------------------
# Sessão MCP
# --------------------------------------------------------------------------------


async def abrir_sessao(sessao: ClientSession) -> None:
    """Negocia a revisão do protocolo: tenta 2026-07-28 (`server/discover`); se o
    servidor for de uma revisão anterior, cai no handshake `initialize`."""
    try:
        await sessao.discover()
    except MCPError:
        await sessao.initialize()


async def ler_ufs(sessao: ClientSession) -> dict[str, str] | None:
    """Lê o recurso de UFs. Ausente ou ilegível -> None, e a saída usa só a sigla.

    O recurso é conveniência de apresentação: a falta dele não pode impedir a consulta.
    """
    try:
        recurso = await sessao.read_resource(URI_UFS)
        dados = json.loads(recurso.contents[0].text)
        return dados if isinstance(dados, dict) else None
    except Exception:
        return None


async def chamar(sessao: ClientSession, ferramenta: str, argumentos: dict[str, str]) -> dict[str, Any]:
    resultado = await sessao.call_tool(ferramenta, argumentos, read_timeout_seconds=TIMEOUT_CHAMADA_S)
    return interpretar_resultado(resultado)


async def executar(cnpj_digitado: str) -> int:
    cnpj = somente_digitos(cnpj_digitado)
    # Com formato inválido não há como pontuar; imprime-se o que o usuário digitou.
    cnpj_impresso = formatar_cnpj(cnpj) if len(cnpj) == 14 else cnpj_digitado

    async with streamable_http_client(URL_SERVIDOR) as (leitura, escrita):
        async with ClientSession(leitura, escrita) as sessao:
            await abrir_sessao(sessao)
            nome = sessao.server_info.name if sessao.server_info else "(servidor não se identificou)"

            listagem = await sessao.list_tools()
            disponiveis = [t.name for t in listagem.tools]
            ausentes = faltando(disponiveis)
            if ausentes:
                print(
                    f"ERRO: o servidor MCP em {URL_SERVIDOR} não publica a(s) ferramenta(s) "
                    f"{', '.join(ausentes)}. Publicadas: {', '.join(disponiveis) or 'nenhuma'}. "
                    "Confira se o endereço aponta para o servidor de CNPJ/CEP e se a versão dele "
                    "é a esperada.",
                    file=sys.stderr,
                )
                return SAIDA_SERVIDOR

            ufs = await ler_ufs(sessao)
            print("\n".join(linhas_cabecalho(nome, disponiveis)))

            try:
                empresa = await chamar(sessao, "consultar_cnpj", {"cnpj": cnpj})
                if "erro" in empresa:
                    # Erro de domínio na primeira consulta: a segunda não é feita.
                    print("\n".join(linhas_erro_dominio("CNPJ", cnpj_impresso, empresa)))
                    return SAIDA_ERRO_DOMINIO

                cep_empresa = somente_digitos(empresa.get("cep", ""))
                endereco = await chamar(sessao, "consultar_cep", {"cep": cep_empresa})
                if "erro" in endereco:
                    print("\n".join([
                        rotulo("CNPJ") + formatar_cnpj(empresa.get("cnpj", "")),
                        rotulo("Razão social") + str(empresa.get("razao_social", "")),
                        *linhas_erro_dominio("CEP", formatar_cep(cep_empresa) or "(vazio no cadastro)", endereco),
                    ]))
                    return SAIDA_ERRO_DOMINIO
            except FalhaFerramenta as falha:
                print(f"FALHA DE INFRAESTRUTURA (reportada pelo servidor): {falha}", file=sys.stderr)
                print("Nada foi impresso como resultado; tente novamente mais tarde.", file=sys.stderr)
                return SAIDA_FALHA_INFRA

            print("\n".join(linhas_resultado(empresa, endereco, ufs)))
            return SAIDA_OK


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("uso: python cliente_cnpj.py <CNPJ>   (ex.: 19.131.243/0001-97)", file=sys.stderr)
        return SAIDA_USO
    try:
        return asyncio.run(executar(argv[1]))
    except Exception as exc:  # noqa: BLE001 — qualquer falha aqui é de conexão/protocolo
        print(
            f"ERRO: não foi possível falar com o servidor MCP em {URL_SERVIDOR} "
            f"({type(exc).__name__}: {exc}). Ele está rodando? "
            "Suba-o com: .venv/bin/python mcp_cnpj/servidor.py",
            file=sys.stderr,
        )
        return SAIDA_SERVIDOR


if __name__ == "__main__":
    sys.exit(main(sys.argv))


# =================================================================================
# SAÍDA REAL DO CLIENTE PARA OS TRÊS CNPJs DE TESTE
# =================================================================================
# Execução real em 2026-10-09, servidor rodando em outro processo
# (.venv/bin/python mcp_cnpj/servidor.py), cliente rodado de dentro de mcp_cnpj/.
# Saída copiada sem edição; a linha [código de saída] foi acrescentada pelo shell.
#
# CNPJs: (1) Raia Drogasil S/A, matriz da rede RD (Drogasil + Raia) — válido, CEP com
# coordenadas; (2) 13 dígitos — formato inválido, barrado no servidor sem chamar a API;
# (3) 98.765.432/0001-98 — dígitos verificadores corretos, inexistente (404 da API).
# Observação: a coordenada devolvida para o CEP 05339-900 (CEP de grande usuário) é a
# de referência da cidade de São Paulo, e não a do imóvel.
#
# $ python cliente_cnpj.py 61.585.865/0001-51
#
# SERVIDOR: cnpj-cep-farmacias   (ferramentas: consultar_cnpj, consultar_cep)
#
# CNPJ ............ 61.585.865/0001-51
# Razão social .... RAIA DROGASIL S/A
# CEP ............. 05339-900
# Endereço ........ Avenida Corifeu de Azevedo Marques 3097 — Vila Butantã, São Paulo/SP
# UF .............. São Paulo (SP)
# Lat / Long ...... -23.5475 / -46.63611
# [código de saída: 0]
#
# $ python cliente_cnpj.py 1234567890123
#
# SERVIDOR: cnpj-cep-farmacias   (ferramentas: consultar_cnpj, consultar_cep)
#
# CNPJ ............ 1234567890123
# Erro ............ CNPJ com 13 dígitos; um CNPJ tem exatamente 14
# Esperado ........ 14 dígitos, com ou sem pontuação (ex.: 61585865000151 ou 61.585.865/0001-51)
# O que fazer ..... Confira se algum dígito foi omitido ou repetido e chame novamente com os 14 dígitos.
# [código de saída: 1]
#
# $ python cliente_cnpj.py 98.765.432/0001-98
#
# SERVIDOR: cnpj-cep-farmacias   (ferramentas: consultar_cnpj, consultar_cep)
#
# CNPJ ............ 98.765.432/0001-98
# Erro ............ CNPJ não encontrado na base da Receita Federal consultada pela BrasilAPI
# Esperado ........ 14 dígitos, com ou sem pontuação (ex.: 61585865000151 ou 61.585.865/0001-51)
# O que fazer ..... O formato está correto, mas o número não corresponde a nenhuma empresa. Confira o número na fonte; não repita a chamada com o mesmo valor.
# [código de saída: 1]
