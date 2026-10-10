"""Testes do Exercício 10 (mcp_cnpj): determinísticos e sem rede.

A BrasilAPI é substituída por `httpx.MockTransport`, então nenhum teste depende de a
API estar no ar nem consome o limite de requisições dela. Cobrem: normalização e
validação de entrada, classificação de erro (200, 404, 400, 429, 500, timeout, falha
de conexão), recorte dos campos devolvidos, o carimbo de versão, o contrato MCP
publicado (ferramentas, descrições, recurso) e a formatação de impressão do cliente.
"""

from __future__ import annotations

import asyncio
import importlib.metadata
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "mcp_cnpj"))

import cliente_cnpj as cli  # noqa: E402
import servidor as srv  # noqa: E402

CNPJ_RD = "61585865000151"  # Raia Drogasil S/A (matriz)
CNPJ_OKBR = "19131243000197"  # Open Knowledge Brasil (exemplo do enunciado)

RESPOSTA_CNPJ = {
    "cnpj": CNPJ_RD, "razao_social": "RAIA DROGASIL S/A", "nome_fantasia": "RD SAUDE",
    "cep": "05339900", "logradouro": "CORIFEU DE AZEVEDO MARQUES 3097", "numero": "3097",
    "complemento": "", "bairro": "VILA BUTANTA", "municipio": "SAO PAULO", "uf": "SP",
    # campos que NÃO devem atravessar a ferramenta:
    "qsa": [{"nome_socio": "FULANO"}], "cnaes_secundarios": [{"codigo": 1}],
    "capital_social": 1, "regime_tributario": [], "email": "x@y", "ddd_telefone_1": "11",
}

RESPOSTA_CEP = {
    "cep": "05339900", "state": "SP", "city": "São Paulo", "neighborhood": "Vila Butantã",
    "street": "Avenida Corifeu de Azevedo Marques 3097", "service": "open-cep",
    "ibge": {"city": "3550308", "state": "35"}, "timezoneName": "America/Sao_Paulo",
    "location": {"type": "Point", "coordinates": {"longitude": "-46.63611", "latitude": "-23.5475"}},
}


def rodar(coro):
    return asyncio.run(coro)


def http_falso(handler) -> httpx.AsyncClient:
    """Cliente HTTP do servidor com a rede trocada por um handler local."""
    return srv.novo_cliente_http(transport=httpx.MockTransport(handler))


def responde(status: int, corpo: object | None = None, texto: str | None = None):
    chamadas: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        chamadas.append(request.url.path)
        if texto is not None:
            return httpx.Response(status, text=texto)
        return httpx.Response(status, json=corpo if corpo is not None else {})

    handler.chamadas = chamadas  # type: ignore[attr-defined]
    return handler


# ------------------------------------------------------------------ carimbo


def test_carimbo_confere_com_sdk_instalado():
    import mcp.types

    assert srv.VERSAO_SDK == importlib.metadata.version("mcp")
    assert srv.REVISAO_PROTOCOLO == mcp.types.LATEST_PROTOCOL_VERSION


def test_timeout_http_explicito():
    assert srv.TIMEOUT_HTTP.read == 10.0 and srv.TIMEOUT_HTTP.connect == 5.0
    # o cliente espera mais que o servidor: quem detecta a lentidão é o servidor
    assert cli.TIMEOUT_CHAMADA_S > srv.TIMEOUT_HTTP.read + srv.TIMEOUT_HTTP.connect


# ------------------------------------------------------------------ normalização / validação


@pytest.mark.parametrize("entrada", ["61.585.865/0001-51", "61585865000151", " 61 585 865 0001 51 "])
def test_cnpj_aceita_pontuacao_e_envia_so_digitos(entrada):
    digitos, erro = srv.validar_cnpj(entrada)
    assert erro is None and digitos == CNPJ_RD


@pytest.mark.parametrize("entrada", ["01311-902", "01311902"])
def test_cep_aceita_hifen(entrada):
    assert srv.validar_cep(entrada) == ("01311902", None)


@pytest.mark.parametrize(
    "entrada, trecho",
    [
        ("1234567890123", "13 dígitos"),
        ("123456789012345", "15 dígitos"),
        ("", "caracteres"),
        ("RAIA DROGASIL", "caracteres"),
        ("6158586500015X", "caracteres"),
        ("61585865000152", "verificadores"),
        ("11111111111111", "verificadores"),
    ],
)
def test_cnpj_formato_invalido_e_erro_de_dominio(entrada, trecho):
    digitos, erro = srv.validar_cnpj(entrada)
    assert digitos is None
    assert trecho in erro["erro"]
    assert erro["recebido"] == entrada
    assert "14 dígitos" in erro["formato_esperado"] and erro["o_que_fazer"]


@pytest.mark.parametrize("entrada, trecho", [("0131190", "7 dígitos"), ("Av Paulista", "caracteres")])
def test_cep_formato_invalido(entrada, trecho):
    digitos, erro = srv.validar_cep(entrada)
    assert digitos is None and trecho in erro["erro"] and "8 dígitos" in erro["formato_esperado"]


def test_digitos_verificadores_de_cnpjs_reais():
    assert srv.digitos_verificadores_cnpj(CNPJ_RD[:12]) == CNPJ_RD[12:]
    assert srv.digitos_verificadores_cnpj(CNPJ_OKBR[:12]) == CNPJ_OKBR[12:]


# ------------------------------------------------------------------ recorte de campos


def test_recorte_cnpj_mantem_so_campos_de_interesse():
    r = srv.recortar_cnpj(RESPOSTA_CNPJ)
    assert set(r) == {"cnpj", "razao_social", "nome_fantasia", "cep", "logradouro", "numero",
                      "complemento", "bairro", "municipio", "uf"}
    assert r["cep"] == "05339900" and r["razao_social"] == "RAIA DROGASIL S/A"


def test_recorte_cep_com_coordenadas():
    r = srv.recortar_cep(RESPOSTA_CEP)
    assert r == {"cep": "05339900", "street": "Avenida Corifeu de Azevedo Marques 3097",
                 "neighborhood": "Vila Butantã", "city": "São Paulo", "state": "SP",
                 "latitude": "-23.5475", "longitude": "-46.63611"}


@pytest.mark.parametrize("location", [{}, {"coordinates": {}}, {"type": "Point", "coordinates": {}}, None])
def test_recorte_cep_sem_coordenadas_vira_null_explicito(location):
    dados = {**RESPOSTA_CEP, "location": location}
    r = srv.recortar_cep(dados)
    assert "latitude" in r and r["latitude"] is None and r["longitude"] is None


# ------------------------------------------------------------------ classificação de erro (HTTP falso)


def test_200_devolve_recorte_e_chama_so_digitos():
    h = responde(200, RESPOSTA_CNPJ)

    async def caso():
        async with http_falso(h) as http:
            return await srv.executar_consulta_cnpj("61.585.865/0001-51", http)

    r = rodar(caso())
    assert r["razao_social"] == "RAIA DROGASIL S/A" and "qsa" not in r
    assert h.chamadas == [f"/api/cnpj/v1/{CNPJ_RD}"]


def test_formato_invalido_nao_chama_a_api():
    h = responde(200, RESPOSTA_CNPJ)

    async def caso():
        async with http_falso(h) as http:
            return await srv.executar_consulta_cnpj("1234567890123", http)

    assert "erro" in rodar(caso()) and h.chamadas == []


@pytest.mark.parametrize("consulta, arg", [("cnpj", "98.765.432/0001-98"), ("cep", "99999-999")])
def test_404_e_erro_de_dominio_como_conteudo(consulta, arg):
    h = responde(404, {"message": "não encontrado", "type": "not_found"})
    fn = srv.executar_consulta_cnpj if consulta == "cnpj" else srv.executar_consulta_cep

    async def caso():
        async with http_falso(h) as http:
            return await fn(arg, http)

    r = rodar(caso())
    assert "não encontrado" in r["erro"] and r["recebido"] == arg and r["o_que_fazer"]


def test_400_e_erro_de_dominio():
    h = responde(400, {"message": "CNPJ inválido"})

    async def caso():
        async with http_falso(h) as http:
            return await srv.executar_consulta_cnpj(CNPJ_RD, http)

    assert "HTTP 400" in rodar(caso())["erro"]


@pytest.mark.parametrize("status", [500, 502, 503, 429])
def test_5xx_e_429_sao_falha_de_infraestrutura(status):
    h = responde(status, {"message": "erro"})

    async def caso():
        async with http_falso(h) as http:
            return await srv.executar_consulta_cep("01311902", http)

    with pytest.raises(srv.FalhaInfraestrutura, match=f"HTTP {status}"):
        rodar(caso())


@pytest.mark.parametrize(
    "excecao, trecho",
    [(httpx.ReadTimeout, "tempo limite"), (httpx.ConnectTimeout, "tempo limite"), (httpx.ConnectError, "conectar")],
)
def test_timeout_e_rede_sao_falha_de_infraestrutura(excecao, trecho):
    def handler(request):
        raise excecao("simulado", request=request)

    async def caso():
        async with http_falso(handler) as http:
            return await srv.executar_consulta_cnpj(CNPJ_RD, http)

    with pytest.raises(srv.FalhaInfraestrutura, match=trecho):
        rodar(caso())


def test_corpo_nao_json_e_falha_de_infraestrutura():
    h = responde(200, texto="<html>manutenção</html>")

    async def caso():
        async with http_falso(h) as http:
            return await srv.executar_consulta_cep("01311902", http)

    with pytest.raises(srv.FalhaInfraestrutura, match="não é JSON"):
        rodar(caso())


# ------------------------------------------------------------------ contrato MCP publicado (em processo)


def test_contrato_publicado_e_falha_vira_is_error(monkeypatch):
    """Lista ferramentas/recurso pelo protocolo e confere que FalhaInfraestrutura chega como isError."""
    from mcp import Client

    def handler(request):
        raise httpx.ReadTimeout("simulado", request=request)

    original = srv.novo_cliente_http
    monkeypatch.setattr(srv, "novo_cliente_http", lambda: original(transport=httpx.MockTransport(handler)))

    async def caso():
        async with Client(srv.servidor) as c:
            ferramentas = {t.name: t for t in (await c.list_tools()).tools}
            falha = await c.call_tool("consultar_cnpj", {"cnpj": CNPJ_RD})
            dominio = await c.call_tool("consultar_cnpj", {"cnpj": "1234567890123"})
            ufs = await c.read_resource("referencia://ufs")
            return ferramentas, falha, dominio, ufs

    ferramentas, falha, dominio, ufs = rodar(caso())
    assert set(ferramentas) == {"consultar_cnpj", "consultar_cep"}
    assert "NÃO faz" in ferramentas["consultar_cnpj"].description
    assert "14 dígitos" in ferramentas["consultar_cnpj"].description
    assert "8 dígitos" in ferramentas["consultar_cep"].description

    assert falha.is_error is True
    with pytest.raises(cli.FalhaFerramenta, match="tempo limite"):
        cli.interpretar_resultado(falha)

    assert dominio.is_error is False
    assert "13 dígitos" in cli.interpretar_resultado(dominio)["erro"]

    assert json.loads(ufs.contents[0].text)["SP"] == "São Paulo"


# ------------------------------------------------------------------ cliente: formatação


def test_cliente_nao_conhece_a_brasilapi():
    assert "brasilapi.com.br" not in (RAIZ / "mcp_cnpj" / "cliente_cnpj.py").read_text(encoding="utf-8")


def test_formatacao_cnpj_cep():
    assert cli.formatar_cnpj(CNPJ_OKBR) == "19.131.243/0001-97"
    assert cli.formatar_cep("01311902") == "01311-902"
    assert cli.formatar_cnpj("1234567890123") == "1234567890123"
    assert cli.somente_digitos("19.131.243/0001-97") == CNPJ_OKBR


def test_rotulos_alinhados_como_no_enunciado():
    assert cli.rotulo("CNPJ") == "CNPJ ............ "
    assert cli.rotulo("Razão social") == "Razão social .... "
    assert cli.rotulo("CEP") == "CEP ............. "
    assert cli.rotulo("Endereço") == "Endereço ........ "
    assert cli.rotulo("Lat / Long") == "Lat / Long ...... "


EMPRESA_OKBR = {"cnpj": CNPJ_OKBR, "razao_social": "OPEN KNOWLEDGE BRASIL", "cep": "01311902"}
CEP_OKBR = {"cep": "01311902", "street": "Avenida Paulista 37", "neighborhood": "Bela Vista",
            "city": "São Paulo", "state": "SP", "latitude": "-23.5475", "longitude": "-46.63611"}


def test_saida_do_enunciado_sem_recurso_de_ufs():
    assert cli.linhas_resultado(EMPRESA_OKBR, CEP_OKBR, None) == [
        "CNPJ ............ 19.131.243/0001-97",
        "Razão social .... OPEN KNOWLEDGE BRASIL",
        "CEP ............. 01311-902",
        "Endereço ........ Avenida Paulista 37 — Bela Vista, São Paulo/SP",
        "Lat / Long ...... -23.5475 / -46.63611",
    ]


def test_saida_com_recurso_de_ufs_e_sem_coordenadas():
    cep = {**CEP_OKBR, "latitude": None, "longitude": None}
    linhas = cli.linhas_resultado(EMPRESA_OKBR, cep, srv.UFS)
    assert "UF .............. São Paulo (SP)" in linhas
    assert linhas[-1] == "Lat / Long ...... não disponível para este CEP"


def test_endereco_do_cep_e_nao_do_cnpj():
    empresa = {**EMPRESA_OKBR, "logradouro": "RUA DO CNPJ", "bairro": "BAIRRO DO CNPJ"}
    linhas = cli.linhas_resultado(empresa, CEP_OKBR, None)
    assert not any("CNPJ" in l for l in linhas if l.startswith("Endereço"))


def test_endereco_de_cep_generico_sem_rua_nem_bairro():
    cep = {"cep": "13825000", "street": "", "neighborhood": "", "city": "Holambra", "state": "SP"}
    assert cli.formatar_endereco(cep) == "Holambra/SP"


def test_erro_de_dominio_impresso_sem_endereco():
    erro = srv.validar_cnpj("1234567890123")[1]
    linhas = cli.linhas_erro_dominio("CNPJ", "1234567890123", erro)
    assert linhas[1] == "Erro ............ CNPJ com 13 dígitos; um CNPJ tem exatamente 14"
    assert not any(l.startswith(("Endereço", "Lat / Long")) for l in linhas)


def test_faltando_ferramentas():
    assert cli.faltando(["consultar_cnpj", "consultar_cep", "outra"]) == []
    assert cli.faltando(["consultar_cnpj"]) == ["consultar_cep"]


def test_interpretar_resultado_sem_saida_estruturada():
    texto = SimpleNamespace(text=json.dumps({"cep": "01311902"}))
    r = SimpleNamespace(is_error=False, structured_content=None, content=[texto])
    assert cli.interpretar_resultado(r) == {"cep": "01311902"}
