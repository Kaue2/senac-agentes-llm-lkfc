"""A instrumentação (Parte 3, §4.2): spans nas convenções GenAI, hierarquia correta mesmo com os
nós do LangGraph rodando em threads, e os atributos de registro da decisão (§2.3)."""

from __future__ import annotations

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from src.grafo.execucao import retomar
from src.observabilidade import telemetria
from src.observabilidade.telemetria import ClienteInstrumentado
from src.versao import SISTEMA_VERSAO
from tests.test_grafo import _call, _msg, _pedir_exportacao, ambiente, triagem_json, turno  # noqa: F401


@pytest.fixture
def spans(monkeypatch):
    exportador = InMemorySpanExporter()
    telemetria.configurar(exportador)
    yield exportador
    monkeypatch.setattr(telemetria, "_provedor", None)


def _por_nome(lista, prefixo):
    return [s for s in lista if s.name.startswith(prefixo)]


def test_turno_gera_raiz_chat_e_ferramenta_com_hierarquia(ambiente, spans):
    ambiente.deps.cliente = ClienteInstrumentado(ambiente.modelo)
    ambiente.modelo.triagens = [triagem_json()]
    ambiente.modelo.passos = [_msg(tool_calls=[_call("consultar_precos", {"produto": "Trayenta 5mg"})]), _msg("R$ 322,15.")]
    turno(ambiente, "preço da trayenta")
    lista = spans.get_finished_spans()
    raiz, = _por_nome(lista, "invoke_agent")
    chats = _por_nome(lista, "chat ")
    ferramenta, = _por_nome(lista, "execute_tool consultar_precos")

    assert raiz.parent is None
    assert len(chats) == 3  # triagem + 2 passos do laço
    # A triagem roda numa thread do LangGraph (em paralelo com a memória): o contexto precisa chegar lá.
    assert all(c.parent is not None and c.parent.span_id == raiz.context.span_id for c in chats)
    assert ferramenta.parent.span_id == raiz.context.span_id
    assert {c.attributes["app.etapa"] for c in chats} == {"triagem", "agente"}
    assert all(c.attributes["gen_ai.operation.name"] == "chat" for c in chats)

    a = raiz.attributes
    assert a["gen_ai.operation.name"] == "invoke_agent"
    assert a["app.versao_sistema"] == SISTEMA_VERSAO
    assert a["app.motivo_terminacao"] == "resposta_final"
    assert a["app.entrada"] == "preço da trayenta"
    assert a["app.prompt.agente"] == "teste@v0"
    assert ferramenta.attributes["gen_ai.tool.name"] == "consultar_precos"
    assert "322.15" in ferramenta.attributes["app.tool.resultado"]


def test_pausa_e_aprovacao_ficam_como_eventos(ambiente, spans):
    r = _pedir_exportacao(ambiente)
    raiz_pausa = _por_nome(spans.get_finished_spans(), "invoke_agent")[-1]
    assert raiz_pausa.attributes["app.motivo_terminacao"] == "pausado_aguardando_humano"
    assert [e.name for e in raiz_pausa.events] == ["aprovacao_solicitada"]

    ambiente.modelo.passos = [_msg("Exportei.")]
    retomar(r.thread_id, {"decisao": "editar", "argumentos": {"explicacao": "revisada"}, "revisor": "adm-01"},
            ambiente.deps, ambiente.grafo, pasta_logs=ambiente.logs)
    raiz = _por_nome(spans.get_finished_spans(), "invoke_agent")[-1]
    eventos = {e.name: e.attributes for e in raiz.events}
    assert raiz.attributes["app.tipo_invocacao"] == "retomada"
    assert eventos["aprovacao_humana"]["app.revisor"] == "adm-01"
    assert eventos["aprovacao_humana"]["app.decisao"] == "editar"
    assert "revisada" in eventos["aprovacao_humana"]["app.argumentos_editados"]
    assert eventos["escrita_executada"]["app.ja_existia"] is False
    exportar, = _por_nome(spans.get_finished_spans(), "execute_tool exportar_analise")
    assert exportar.parent.span_id == raiz.context.span_id


def test_erro_do_modelo_marca_o_span_chat(spans):
    class Quebrado:
        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    raise RuntimeError("caiu")

    with pytest.raises(RuntimeError):
        ClienteInstrumentado(Quebrado()).chat.completions.create(model="m", messages=[])
    s, = spans.get_finished_spans()
    assert s.name == "chat m" and s.attributes["error.type"] == "RuntimeError"
