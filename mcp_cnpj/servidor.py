"""Servidor MCP de CNPJ e CEP (Exercício 10) — conferir a matriz de uma rede concorrente.

Cenário no case do grupo (BI de preços de farmácia, docs/case.md): o painel compara
preços de 13 redes (Araujo, Drogasil, Raia, Pacheco, Venancio, DPSP, Globo, Indiana,
Nissei, Pague Menos, Panvel, São João...). Antes de atribuir uma coleta a uma rede, o
time confere quem é a pessoa jurídica por trás dela e onde fica a matriz. Este servidor
publica essa conferência como duas ferramentas MCP sobre a BrasilAPI:

    consultar_cnpj(cnpj) -> razão social, nome fantasia, CEP e endereço cadastral
    consultar_cep(cep)   -> logradouro, bairro, cidade, UF e coordenadas

e um recurso, `referencia://ufs`, com a tabela sigla -> nome da UF por extenso.

O servidor NÃO sabe que as duas ferramentas são usadas em sequência. O encadeamento
CNPJ -> CEP é decisão do cliente (cliente_cnpj.py) ou de um agente; `consultar_cep`
continua servindo a quem só tem um CEP na mão.

Como rodar (processo próprio, num terminal separado):

    .venv/bin/python mcp_cnpj/servidor.py
    # escuta em http://127.0.0.1:8000/mcp (Streamable HTTP)
    # porta configurável por MCP_CNPJ_PORTA

-----------------------------------------------------------------------------------
CARIMBO (o que muda o comportamento observado deste servidor)
-----------------------------------------------------------------------------------
- Revisão da especificação MCP: 2026-07-28
    (= mcp.types.LATEST_PROTOCOL_VERSION no SDK instalado; é a revisão negociada
    com o cliente_cnpj.py via `server/discover`. O mesmo SDK ainda aceita clientes
    antigos pelo handshake `initialize`, até a revisão 2025-11-25.)
- SDK Python `mcp`: 2.3.0
    (no SDK 2.x a classe FastMCP das notas de aula foi renomeada para
    `mcp.server.mcpserver.MCPServer`; a API de decorators é a mesma.)
- Fonte de dados: BrasilAPI, endpoints /cnpj/v1 e /cep/v2.
- Versão deste servidor (contrato das ferramentas): 1.0.0

Por que registrar: num servidor de terceiro, quem muda esses números é outra pessoa,
sem aviso e sem que a resposta deixe de ser sintaticamente válida. As constantes
REVISAO_PROTOCOLO e VERSAO_SDK abaixo são conferidas contra o pacote instalado em
tests/test_mcp_cnpj.py: uma atualização silenciosa do SDK quebra o teste em vez de
mudar o comportamento sem ninguém perceber.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

# --------------------------------------------------------------------------------
# Carimbo e parâmetros
# --------------------------------------------------------------------------------

REVISAO_PROTOCOLO = "2026-07-28"
VERSAO_SDK = "2.3.0"
VERSAO_SERVIDOR = "1.0.0"

NOME_SERVIDOR = "cnpj-cep-farmacias"

URL_BRASILAPI = "https://brasilapi.com.br/api"

# Timeout HTTP explícito. Sem ele, uma BrasilAPI lenta prende a ferramenta, e com ela
# o cliente MCP que espera a resposta. Valores:
#   - connect=5s: estabelecer TCP+TLS com um serviço público saudável leva bem menos de
#     1s; 5s cobre rede ruim sem esperar por um host que não vai responder.
#   - read=10s: a rota /cep/v2 consulta vários provedores em cascata (Correios,
#     ViaCEP, OpenCEP...) antes de responder, e a de CNPJ consulta a base da Receita;
#     respostas normais vêm em 1-3s. 10s dá folga para o pior caso razoável e ainda
#     fica abaixo do timeout de leitura do cliente (30s), de modo que é o servidor
#     quem detecta a lentidão e devolve uma falha classificada — e não o cliente
#     que desiste sem saber por quê.
TIMEOUT_HTTP = httpx.Timeout(10.0, connect=5.0)

# Identificar o chamador é cortesia com uma API pública e gratuita, e facilita para
# o mantenedor distinguir este tráfego se algum dia ele causar problema.
CABECALHOS_HTTP = {"User-Agent": f"{NOME_SERVIDOR}/{VERSAO_SERVIDOR} (exercicio academico)"}

# Só dígitos e os separadores usuais. Qualquer outro caractere (letra, por exemplo)
# indica que o argumento não é um CNPJ/CEP — e removê-lo em silêncio transformaria
# "12abc345..." num número que o usuário nunca digitou.
_PADRAO_ENTRADA = re.compile(r"[\d.\-/\s]+")

# --------------------------------------------------------------------------------
# Recurso: UFs por extenso (desafio opcional B)
# --------------------------------------------------------------------------------

UFS: dict[str, str] = {
    "AC": "Acre", "AL": "Alagoas", "AP": "Amapá", "AM": "Amazonas", "BA": "Bahia",
    "CE": "Ceará", "DF": "Distrito Federal", "ES": "Espírito Santo", "GO": "Goiás",
    "MA": "Maranhão", "MT": "Mato Grosso", "MS": "Mato Grosso do Sul",
    "MG": "Minas Gerais", "PA": "Pará", "PB": "Paraíba", "PR": "Paraná",
    "PE": "Pernambuco", "PI": "Piauí", "RJ": "Rio de Janeiro",
    "RN": "Rio Grande do Norte", "RS": "Rio Grande do Sul", "RO": "Rondônia",
    "RR": "Roraima", "SC": "Santa Catarina", "SP": "São Paulo", "SE": "Sergipe",
    "TO": "Tocantins",
}


# --------------------------------------------------------------------------------
# Funções puras (sem rede) — testadas isoladamente em tests/test_mcp_cnpj.py
# --------------------------------------------------------------------------------


def erro_dominio(erro: str, recebido: str, formato_esperado: str, o_que_fazer: str) -> dict[str, Any]:
    """Monta o erro de DOMÍNIO, que volta como conteúdo (resultado normal da ferramenta).

    As três perguntas que uma mensagem de erro precisa responder para quem a lê — um
    cliente determinístico ou um modelo — estão em campos separados: o que errou
    (`erro`), qual era o certo (`formato_esperado`) e o que fazer agora
    (`o_que_fazer`). `recebido` devolve o argumento como chegou, para o leitor
    comparar com o esperado sem precisar lembrar o que mandou.
    """
    return {
        "erro": erro,
        "recebido": recebido,
        "formato_esperado": formato_esperado,
        "o_que_fazer": o_que_fazer,
    }


def normalizar_digitos(valor: str) -> str | None:
    """Remove pontuação e espaços; devolve None se houver caractere que não seja separador.

    Aceita '19.131.243/0001-97' e '01311-902'. Rejeita 'abc' e '1913124300019X' em vez
    de descartar as letras em silêncio — o que impede que uma entrada malformada vire
    um número diferente do que o usuário digitou.
    """
    valor = (valor or "").strip()
    if not valor or not _PADRAO_ENTRADA.fullmatch(valor):
        return None
    return re.sub(r"\D", "", valor)


def digitos_verificadores_cnpj(base12: str) -> str:
    """Calcula os dois dígitos verificadores de um CNPJ a partir dos 12 primeiros dígitos."""

    def _dv(digitos: str, pesos: list[int]) -> str:
        resto = sum(int(d) * p for d, p in zip(digitos, pesos)) % 11
        return "0" if resto < 2 else str(11 - resto)

    pesos1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    d1 = _dv(base12, pesos1)
    d2 = _dv(base12 + d1, [6] + pesos1)
    return d1 + d2


FORMATO_CNPJ = "14 dígitos, com ou sem pontuação (ex.: 61585865000151 ou 61.585.865/0001-51)"
FORMATO_CEP = "8 dígitos, com ou sem hífen (ex.: 01311902 ou 01311-902)"


def validar_cnpj(cnpj: str) -> tuple[str | None, dict[str, Any] | None]:
    """Normaliza e valida o formato do CNPJ, sem rede. Devolve (dígitos, None) ou (None, erro).

    Verificar os dígitos verificadores aqui, e não deixar para a API, poupa uma
    requisição de uma API com limite de uso e dá uma mensagem mais precisa do que um
    404 genérico: "o número foi digitado errado" é diferente de "o número não existe".
    """
    digitos = normalizar_digitos(cnpj)
    if digitos is None:
        return None, erro_dominio(
            "CNPJ contém caracteres que não são dígitos nem pontuação",
            cnpj, FORMATO_CNPJ,
            "Envie apenas os números do CNPJ; não passe nome de empresa nem texto livre.",
        )
    if len(digitos) != 14:
        return None, erro_dominio(
            f"CNPJ com {len(digitos)} dígitos; um CNPJ tem exatamente 14",
            cnpj, FORMATO_CNPJ,
            "Confira se algum dígito foi omitido ou repetido e chame novamente com os 14 dígitos.",
        )
    if len(set(digitos)) == 1 or digitos[12:] != digitos_verificadores_cnpj(digitos[:12]):
        return None, erro_dominio(
            "CNPJ com dígitos verificadores inválidos (os dois últimos dígitos não conferem)",
            cnpj, FORMATO_CNPJ,
            "O número foi digitado ou copiado errado; confira-o na fonte e chame novamente.",
        )
    return digitos, None


def validar_cep(cep: str) -> tuple[str | None, dict[str, Any] | None]:
    """Normaliza e valida o formato do CEP, sem rede. Devolve (dígitos, None) ou (None, erro)."""
    digitos = normalizar_digitos(cep)
    if digitos is None:
        return None, erro_dominio(
            "CEP contém caracteres que não são dígitos nem hífen",
            cep, FORMATO_CEP,
            "Envie apenas os números do CEP. Esta ferramenta não busca por nome de rua nem de cidade.",
        )
    if len(digitos) != 8:
        return None, erro_dominio(
            f"CEP com {len(digitos)} dígitos; um CEP tem exatamente 8",
            cep, FORMATO_CEP,
            "Confira o CEP e chame novamente com os 8 dígitos.",
        )
    return digitos, None


def recortar_cnpj(dados: dict[str, Any]) -> dict[str, Any]:
    """Reduz a resposta da BrasilAPI /cnpj/v1 aos campos que interessam.

    A resposta completa tem ~50 campos (quadro societário, CNAEs secundários, regime
    tributário, opção pelo Simples...). Tudo o que a ferramenta devolve é texto que o
    cliente — ou o contexto de um modelo — carrega; devolver o JSON inteiro custaria
    contexto sem servir a pergunta "quem é e onde fica a matriz desta rede".

    Campos mantidos, e por quê:
      - cnpj: identifica sem ambiguidade o registro devolvido (o leitor confere que é
        o que pediu).
      - razao_social: nome jurídico; é o que distingue, por exemplo, RAIA DROGASIL S/A
        de uma farmácia independente que usa "Drogasil" no letreiro.
      - nome_fantasia: nome comercial ("RD SAUDE"); é por ele que o BI casa a pessoa
        jurídica com uma das 13 redes monitoradas.
      - cep: a chave para a segunda consulta (consultar_cep); vem só com dígitos.
      - logradouro, numero, complemento, bairro, municipio, uf: o endereço como está
        no cadastro da Receita. Ficam para quem não vai consultar o CEP; o cliente
        deste exercício usa o endereço da consulta de CEP.

    Ficam de fora: sócios (dado pessoal sem uso aqui), CNAEs, capital social, regime
    tributário, telefones e e-mail.
    """
    campos = ("cnpj", "razao_social", "nome_fantasia", "cep", "logradouro", "numero",
              "complemento", "bairro", "municipio", "uf")
    return {campo: (dados.get(campo) or "") for campo in campos}


def recortar_cep(dados: dict[str, Any]) -> dict[str, Any]:
    """Reduz a resposta da BrasilAPI /cep/v2 aos campos que interessam.

    Campos mantidos, e por quê:
      - cep: confirma qual CEP foi resolvido.
      - street, neighborhood, city, state: o endereço que o cliente apresenta.
      - latitude, longitude: o motivo de usar /cep/v2 e não /cep/v1; servem para pôr a
        matriz no mapa. Vêm como texto, exatamente como a API devolve, para não
        introduzir arredondamento de ponto flutuante.

    Coordenadas ausentes (`location.coordinates` vazio, o que acontece para parte dos
    CEPs) viram `null` explícito em vez de sumirem: assim o leitor distingue "o CEP não
    tem coordenadas" de "a ferramenta esqueceu o campo".

    Ficam de fora: `service` (qual provedor respondeu), códigos IBGE e fuso horário.
    """
    coordenadas = ((dados.get("location") or {}).get("coordinates") or {})
    return {
        "cep": dados.get("cep") or "",
        "street": dados.get("street") or "",
        "neighborhood": dados.get("neighborhood") or "",
        "city": dados.get("city") or "",
        "state": dados.get("state") or "",
        "latitude": coordenadas.get("latitude") or None,
        "longitude": coordenadas.get("longitude") or None,
    }


# --------------------------------------------------------------------------------
# Chamada HTTP com erro classificado
# --------------------------------------------------------------------------------


class FalhaInfraestrutura(ToolError):
    """Erro de INFRAESTRUTURA: BrasilAPI fora do ar, timeout, 5xx, limite de requisições.

    Herda de ToolError porque é assim que o SDK devolve uma falha ao cliente: a
    chamada volta com `isError=true` e a mensagem no conteúdo. O cliente trata isso
    como falha (não como dado), e um agente sabe que repetir com outro argumento não
    resolve. O que isso impede: um erro de rede devolvido como resultado normal faria
    um modelo reformular o argumento educadamente até estourar o orçamento.
    """


def novo_cliente_http(transport: httpx.AsyncBaseTransport | None = None) -> httpx.AsyncClient:
    """Cria o cliente HTTP com timeout e cabeçalhos fixos. `transport` existe para os testes."""
    return httpx.AsyncClient(
        base_url=URL_BRASILAPI, timeout=TIMEOUT_HTTP, headers=CABECALHOS_HTTP, transport=transport
    )


async def obter_json(http: httpx.AsyncClient, caminho: str) -> tuple[int, dict[str, Any]]:
    """GET na BrasilAPI. Devolve (status, json) para 2xx/4xx; levanta FalhaInfraestrutura no resto.

    Classificação:
      - timeout, erro de conexão/DNS                 -> infraestrutura
      - 5xx                                          -> infraestrutura
      - 429 (limite de requisições excedido)         -> infraestrutura: o argumento
        estava certo, e quem resolve é esperar, não corrigir o pedido
      - corpo que não é JSON                         -> infraestrutura
      - 2xx e os demais 4xx (400, 404)               -> devolvidos ao chamador, que os
        interpreta como resultado ou erro de domínio
    """
    try:
        resposta = await http.get(caminho)
    except httpx.TimeoutException as exc:
        raise FalhaInfraestrutura(
            f"BrasilAPI não respondeu dentro do tempo limite ({type(exc).__name__}). "
            "Falha temporária de infraestrutura; tente novamente em alguns instantes."
        ) from exc
    except httpx.RequestError as exc:
        raise FalhaInfraestrutura(
            f"Não foi possível conectar à BrasilAPI ({type(exc).__name__}). "
            "Falha de rede ou serviço fora do ar; tente novamente mais tarde."
        ) from exc

    if resposta.status_code == 429 or resposta.status_code >= 500:
        raise FalhaInfraestrutura(
            f"BrasilAPI respondeu HTTP {resposta.status_code}. Falha do serviço externo, não do "
            "argumento enviado; tente novamente mais tarde."
        )
    try:
        corpo = resposta.json()
    except ValueError as exc:
        raise FalhaInfraestrutura(
            f"BrasilAPI respondeu HTTP {resposta.status_code} com corpo que não é JSON."
        ) from exc
    if not isinstance(corpo, dict):
        raise FalhaInfraestrutura(f"BrasilAPI respondeu HTTP {resposta.status_code} com JSON inesperado.")
    return resposta.status_code, corpo


async def executar_consulta_cnpj(cnpj: str, http: httpx.AsyncClient) -> dict[str, Any]:
    """Corpo de `consultar_cnpj`, com o cliente HTTP injetado (testável sem rede)."""
    digitos, erro = validar_cnpj(cnpj)
    if erro:
        return erro
    status, corpo = await obter_json(http, f"/cnpj/v1/{digitos}")
    if status == 404:
        return erro_dominio(
            "CNPJ não encontrado na base da Receita Federal consultada pela BrasilAPI",
            cnpj, FORMATO_CNPJ,
            "O formato está correto, mas o número não corresponde a nenhuma empresa. "
            "Confira o número na fonte; não repita a chamada com o mesmo valor.",
        )
    if status >= 400:
        return erro_dominio(
            f"BrasilAPI recusou o CNPJ (HTTP {status}): {corpo.get('message', 'sem detalhe')}",
            cnpj, FORMATO_CNPJ,
            "Confira o número e chame novamente com um CNPJ válido.",
        )
    return recortar_cnpj(corpo)


async def executar_consulta_cep(cep: str, http: httpx.AsyncClient) -> dict[str, Any]:
    """Corpo de `consultar_cep`, com o cliente HTTP injetado (testável sem rede)."""
    digitos, erro = validar_cep(cep)
    if erro:
        return erro
    status, corpo = await obter_json(http, f"/cep/v2/{digitos}")
    if status == 404:
        return erro_dominio(
            "CEP não encontrado em nenhum dos provedores consultados pela BrasilAPI",
            cep, FORMATO_CEP,
            "Confira o CEP na fonte; não repita a chamada com o mesmo valor.",
        )
    if status >= 400:
        return erro_dominio(
            f"BrasilAPI recusou o CEP (HTTP {status}): {corpo.get('message', 'sem detalhe')}",
            cep, FORMATO_CEP,
            "Confira o CEP e chame novamente com 8 dígitos.",
        )
    return recortar_cep(corpo)


# --------------------------------------------------------------------------------
# Servidor MCP
# --------------------------------------------------------------------------------

servidor = MCPServer(NOME_SERVIDOR, version=VERSAO_SERVIDOR)


# As docstrings abaixo SÃO a descrição publicada de cada ferramenta: é o texto que um
# agente de terceiro lê para decidir se e como chamá-la. Por isso dizem o que a
# ferramenta faz, o formato exato do argumento e o que ela NÃO faz.


@servidor.tool()
async def consultar_cnpj(cnpj: str) -> dict[str, Any]:
    """Consulta o cadastro de uma empresa na Receita Federal (via BrasilAPI) pelo CNPJ.

    Uso típico: conferir quem é a pessoa jurídica de uma rede de farmácias e onde fica
    o estabelecimento cadastrado sob aquele CNPJ (a matriz, quando o CNPJ termina em
    0001-XX).

    Argumento `cnpj`: exatamente 14 dígitos. Aceita com ou sem pontuação
    ("61585865000151" ou "61.585.865/0001-51"). Os dígitos verificadores são conferidos.

    Devolve: cnpj, razao_social, nome_fantasia, cep (8 dígitos, sem hífen, pronto para
    consultar_cep), logradouro, numero, complemento, bairro, municipio, uf.

    NÃO faz: não devolve latitude/longitude (use consultar_cep com o `cep` devolvido);
    não busca empresa por nome, marca ou razão social; não lista as filiais de uma rede;
    não devolve sócios, CNAEs nem dados tributários.

    Erros de argumento (formato inválido, CNPJ inexistente) voltam como resultado com o
    campo `erro`, junto com `formato_esperado` e `o_que_fazer`. Falhas da BrasilAPI
    (fora do ar, lentidão, limite de uso) voltam como erro da chamada: não adianta
    trocar o argumento, só tentar de novo mais tarde.
    """
    async with novo_cliente_http() as http:
        return await executar_consulta_cnpj(cnpj, http)


@servidor.tool()
async def consultar_cep(cep: str) -> dict[str, Any]:
    """Consulta um CEP brasileiro (via BrasilAPI) e devolve endereço e coordenadas.

    Argumento `cep`: exatamente 8 dígitos. Aceita com ou sem hífen ("01311902" ou
    "01311-902").

    Devolve: cep, street (logradouro), neighborhood (bairro), city, state (sigla da UF),
    latitude, longitude. latitude e longitude podem vir null: nem todo CEP tem
    coordenadas na base; isso não é erro. Para CEPs genéricos ou de grandes usuários a
    coordenada pode ser a de referência da cidade, e não a do imóvel.

    NÃO faz: não busca CEP por nome de rua, bairro ou cidade; não consulta empresas (use
    consultar_cnpj); não calcula distância nem rota.

    Erros de argumento (formato inválido, CEP inexistente) voltam como resultado com o
    campo `erro`, junto com `formato_esperado` e `o_que_fazer`. Falhas da BrasilAPI
    voltam como erro da chamada.
    """
    async with novo_cliente_http() as http:
        return await executar_consulta_cep(cep, http)


@servidor.resource(
    "referencia://ufs",
    name="ufs",
    description="Tabela das 27 UFs do Brasil: sigla -> nome por extenso (JSON).",
    mime_type="application/json",
)
def ufs() -> str:
    """Lista de UFs por extenso, para apresentar "São Paulo (SP)" em vez de "SP".

    Por que RECURSO e não ferramenta: é um dado estático, que não depende de pergunta
    nenhuma, e que a APLICAÇÃO sabe de antemão que vai precisar. Recurso é o que a
    aplicação decide incluir; ferramenta é o que o modelo decide invocar. Como
    ferramenta, um agente teria de "decidir" chamá-la — e poderia não chamar e inventar
    o nome do estado, ou chamar a cada resposta, gastando uma volta do laço e uma
    declaração a mais no contexto. Como recurso, o cliente lê uma vez no início da
    sessão e o modelo nem precisa saber que ele existe.
    """
    return json.dumps(UFS, ensure_ascii=False)


if __name__ == "__main__":
    # Host 127.0.0.1: o servidor só aceita conexões da própria máquina; o SDK ainda
    # ativa a proteção contra DNS rebinding para hosts locais.
    servidor.run(
        transport="streamable-http",
        host="127.0.0.1",
        port=int(os.environ.get("MCP_CNPJ_PORTA", "8000")),
    )
