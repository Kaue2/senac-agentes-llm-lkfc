"""Traces nas convenções semânticas GenAI do OpenTelemetry (Parte 3, §4.2).

Três tipos de span, os da convenção:

| Span | Aberto em | Atributos GenAI |
|---|---|---|
| `invoke_agent agente-bi-farmacia` | `src/grafo/execucao.py::_invocar`, uma vez por invocação (turno ou retomada), como raiz | `gen_ai.operation.name`, `gen_ai.agent.name`, `gen_ai.provider.name`, `gen_ai.request.model` |
| `chat <modelo>` | `ClienteInstrumentado`, a cada chamada ao modelo | `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `gen_ai.response.finish_reasons` |
| `execute_tool <ferramenta>` | `rastrear_ferramenta`, a cada ferramenta executada pelo grafo | `gen_ai.tool.name`, `gen_ai.tool.call.id` |

Atributos próprios do case ficam no prefixo `app.` — os da raiz estão em docs/observabilidade.md
§2, e incluem os dois obrigatórios: `app.motivo_terminacao` e `app.versao_sistema`.

O trace é também o REGISTRO DA DECISÃO (§2.3): a raiz guarda a entrada (já mascarada, quando o
controle de dado pessoal estiver ligado), as versões, a saída e o motivo de término; o span da
ferramenta guarda argumentos e resultado (truncado) e os ids dos trechos do corpus; a aprovação
humana é um evento na raiz da retomada.

Destino: arquivo JSONL (um span por linha) em `logs/traces/`, consultável com
`python -m src.observabilidade.ver`. `OTEL_ARQUIVO_TRACES` troca o arquivo; `OTEL_DESLIGADO=1`
desliga a exportação.
"""

from __future__ import annotations

import json
import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Sequence

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.trace import Status, StatusCode

from src.versao import SISTEMA_VERSAO

NOME_AGENTE = "agente-bi-farmacia"
PASTA_TRACES = Path(__file__).resolve().parents[2] / "logs" / "traces"
MAX_CARACTERES_ATRIBUTO = 2000
_lock = threading.Lock()
_provedor: TracerProvider | None = None


class ExportadorJsonl(SpanExporter):
    """Um span por linha, em JSON compacto. Arquivo é o destino mais simples que é consultável
    (grep, jq, o visualizador do projeto) e que vai para o repositório quando um documento cita
    um trace."""

    def __init__(self, caminho: Path) -> None:
        self.caminho = caminho
        caminho.parent.mkdir(parents=True, exist_ok=True)

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        linhas = [json.dumps(json.loads(s.to_json()), ensure_ascii=False, separators=(",", ":")) for s in spans]
        with _lock, self.caminho.open("a", encoding="utf-8") as f:
            f.write("\n".join(linhas) + "\n")
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:  # nada a fechar: o arquivo é aberto a cada exportação
        pass


def arquivo_padrao() -> Path:
    if os.environ.get("OTEL_ARQUIVO_TRACES"):
        return Path(os.environ["OTEL_ARQUIVO_TRACES"])
    from datetime import date

    return PASTA_TRACES / f"traces-{date.today().isoformat()}.jsonl"


def configurar(exportador: SpanExporter | None = None) -> TracerProvider:
    """Configura o provedor uma vez por processo. Testes passam um exportador em memória."""
    global _provedor
    with _lock:
        if _provedor is not None and exportador is None:
            return _provedor
        provedor = TracerProvider(resource=Resource.create({"service.name": NOME_AGENTE, "service.version": SISTEMA_VERSAO}))
        if exportador is None and os.environ.get("OTEL_DESLIGADO") != "1":
            exportador = ExportadorJsonl(arquivo_padrao())
        if exportador is not None:
            provedor.add_span_processor(SimpleSpanProcessor(exportador))
        _provedor = provedor
        return provedor


def tracer() -> trace.Tracer:
    return configurar().get_tracer("src.observabilidade", SISTEMA_VERSAO)


def texto_curto(valor: Any) -> str:
    texto = valor if isinstance(valor, str) else json.dumps(valor, ensure_ascii=False, default=str)
    return texto if len(texto) <= MAX_CARACTERES_ATRIBUTO else texto[:MAX_CARACTERES_ATRIBUTO] + "…(truncado)"


@contextmanager
def span_raiz(tipo: str, thread_id: str, modelo: str, atributos: dict[str, Any]) -> Iterator[trace.Span]:
    with tracer().start_as_current_span(f"invoke_agent {NOME_AGENTE}") as span:
        span.set_attributes({
            "gen_ai.operation.name": "invoke_agent",
            "gen_ai.agent.name": NOME_AGENTE,
            "gen_ai.provider.name": "openai_compatible",
            "gen_ai.request.model": modelo,
            "app.versao_sistema": SISTEMA_VERSAO,
            "app.tipo_invocacao": tipo,
            "app.thread_id": thread_id,
            **{k: v for k, v in atributos.items() if v is not None},
        })
        yield span


@contextmanager
def rastrear_ferramenta(nome: str, tool_call_id: str, argumentos: dict) -> Iterator[dict]:
    """Abre `execute_tool <nome>`; quem chama preenche `registro["resultado"]` antes de sair."""
    registro: dict[str, Any] = {}
    with tracer().start_as_current_span(f"execute_tool {nome}") as span:
        span.set_attributes({
            "gen_ai.operation.name": "execute_tool",
            "gen_ai.tool.name": nome,
            "gen_ai.tool.call.id": tool_call_id,
            "app.tool.argumentos": texto_curto(argumentos),
        })
        yield registro
        resultado = registro.get("resultado") or {}
        span.set_attribute("app.tool.resultado", texto_curto(resultado))
        if isinstance(resultado, dict):
            if "erro" in resultado:
                span.set_attribute("app.tool.erro", str(resultado["erro"])[:300])
                span.set_status(Status(StatusCode.ERROR, "erro de ferramenta (recuperável)"))
            if "encontrado" in resultado:
                span.set_attribute("app.tool.encontrado", bool(resultado["encontrado"]))
            trechos = [t.get("id") for t in resultado.get("trechos", []) if isinstance(t, dict)]
            if trechos:
                span.set_attribute("app.rag.trechos", trechos)


class _Completions:
    def __init__(self, original: Any) -> None:
        self._original = original

    def create(self, **kwargs: Any) -> Any:
        modelo = kwargs.get("model", "?")
        etapa = "triagem" if kwargs.get("response_format") else "agente"
        with tracer().start_as_current_span(f"chat {modelo}") as span:
            span.set_attributes({
                "gen_ai.operation.name": "chat",
                "gen_ai.request.model": modelo,
                "app.etapa": etapa,
                "app.mensagens_enviadas": len(kwargs.get("messages", [])),
            })
            try:
                resposta = self._original.create(**kwargs)
            except Exception as exc:
                span.set_attribute("error.type", type(exc).__name__)
                span.set_status(Status(StatusCode.ERROR, str(exc)[:300]))
                raise
            uso = getattr(resposta, "usage", None)
            if uso is not None:
                entrada = getattr(uso, "prompt_tokens", None)
                saida = getattr(uso, "completion_tokens", None)
                if entrada is not None:
                    span.set_attribute("gen_ai.usage.input_tokens", int(entrada))
                if saida is not None:
                    span.set_attribute("gen_ai.usage.output_tokens", int(saida))
                total = getattr(uso, "total_tokens", None)
                if total is not None:
                    span.set_attribute("app.usage.total_tokens", int(total))
            escolhas = getattr(resposta, "choices", None) or []
            motivos = [getattr(c, "finish_reason", None) for c in escolhas]
            if any(motivos):
                span.set_attribute("gen_ai.response.finish_reasons", [m for m in motivos if m])
            if getattr(resposta, "model", None):
                span.set_attribute("gen_ai.response.model", str(resposta.model))
            return resposta


class ClienteInstrumentado:
    """Envolve um cliente com a interface `chat.completions.create` da biblioteca openai e abre um
    span `chat` por chamada. O resto da interface passa direto."""

    def __init__(self, cliente: Any) -> None:
        self._cliente = cliente
        self.chat = type("Chat", (), {})()
        self.chat.completions = _Completions(cliente.chat.completions)

    def __getattr__(self, nome: str) -> Any:
        return getattr(self._cliente, nome)
