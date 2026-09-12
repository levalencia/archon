"""Contract tests for vendor-neutral application telemetry."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from opentelemetry.exporter.otlp.proto.grpc import trace_exporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.trace import export as trace_sdk_export
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.config import Settings
from app.observability.otel_exporter import OTLPExporter
from app.observability.tracing import Span


@pytest.mark.unit
def test_application_owns_provider_and_exports_only_to_collector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = InMemorySpanExporter()
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        trace_exporter,
        "OTLPSpanExporter",
        lambda **kwargs: calls.append(kwargs) or captured,
    )
    monkeypatch.setattr(
        trace_sdk_export,
        "BatchSpanProcessor",
        lambda exporter: SimpleSpanProcessor(exporter),
    )

    exporter = OTLPExporter("cogentrex-test", "http://otel-collector:4317")
    exporter.export_span(Span("probe"))
    assert exporter.force_flush() is True

    assert exporter.is_active is True
    assert calls == [{"endpoint": "http://otel-collector:4317", "insecure": True}]
    assert [span.name for span in captured.get_finished_spans()] == ["probe"]
    exporter.shutdown()


@pytest.mark.unit
def test_fastapi_instrumentation_uses_safe_standard_otel_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[FastAPI, dict[str, object]]] = []
    monkeypatch.setattr(
        FastAPIInstrumentor,
        "instrument_app",
        lambda self, app, **kwargs: calls.append((app, kwargs)),
    )
    exporter = OTLPExporter("cogentrex-test", "http://otel-collector:4317")
    app = FastAPI()

    assert exporter.instrument_fastapi(app) is True
    assert calls == [
        (
            app,
            {
                "tracer_provider": exporter._provider,
                "http_capture_headers_server_request": [],
                "http_capture_headers_server_response": [],
                "exclude_spans": ["send", "receive"],
            },
        )
    ]
    exporter.shutdown()


@pytest.mark.unit
def test_standard_provider_exports_cogentrex_spans_to_collector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = InMemorySpanExporter()
    monkeypatch.delenv("LOGFIRE_TOKEN", raising=False)
    monkeypatch.setattr(trace_exporter, "OTLPSpanExporter", lambda **_kwargs: captured)
    monkeypatch.setattr(
        trace_sdk_export,
        "BatchSpanProcessor",
        lambda exporter: SimpleSpanProcessor(exporter),
    )

    exporter = OTLPExporter("cogentrex-real-test", "http://otel-collector:4317")
    exporter.export_span(
        Span(
            "invoke_agent Cogentrex",
            {
                "gen_ai.operation.name": "invoke_agent",
                "gen_ai.agent.name": "Cogentrex",
            },
        )
    )
    with exporter.start_span("rag.query", {"rag.top_k": 5}):
        pass
    exporter.trace_llm_call("model-a", "provider-a", 10, 5, 12.5)
    exporter.trace_tool_call("web_search", 3.5)
    assert exporter.force_flush() is True

    names = {span.name for span in captured.get_finished_spans()}
    assert {
        "invoke_agent Cogentrex",
        "rag.query",
        "chat model-a",
        "execute_tool web_search",
    } <= names
    agent_span = next(
        span for span in captured.get_finished_spans() if span.name == "invoke_agent Cogentrex"
    )
    agent_attributes = dict(agent_span.attributes or {})
    assert agent_attributes["gen_ai.operation.name"] == "invoke_agent"
    assert agent_attributes["gen_ai.agent.name"] == "Cogentrex"
    exporter.shutdown()


@pytest.mark.unit
def test_tool_span_is_a_child_of_the_active_agent_span(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = InMemorySpanExporter()
    monkeypatch.delenv("LOGFIRE_TOKEN", raising=False)
    monkeypatch.setattr(trace_exporter, "OTLPSpanExporter", lambda **_kwargs: captured)
    monkeypatch.setattr(
        trace_sdk_export,
        "BatchSpanProcessor",
        lambda exporter: SimpleSpanProcessor(exporter),
    )
    exporter = OTLPExporter("cogentrex-agent-tree-test", "http://otel-collector:4317")
    agent = Span(
        "invoke_agent Cogentrex",
        {
            "cogentrex.run.id": "run-1",
            "gen_ai.operation.name": "invoke_agent",
            "gen_ai.agent.name": "Cogentrex",
        },
    )
    tool = Span(
        "execute_tool calculator",
        {
            "cogentrex.run.id": "run-1",
            "gen_ai.operation.name": "execute_tool",
            "gen_ai.tool.name": "calculator",
        },
    )

    exporter.start_agent_span(agent)
    exporter.export_span(tool)
    exporter.finish_agent_span(agent)
    exporter.force_flush()

    spans = {span.name: span for span in captured.get_finished_spans()}
    tool_span = spans["execute_tool calculator"]
    agent_span = spans["invoke_agent Cogentrex"]
    assert tool_span.context is not None
    assert tool_span.parent is not None
    assert agent_span.context is not None
    assert tool_span.context.trace_id == agent_span.context.trace_id
    assert tool_span.parent.span_id == agent_span.context.span_id
    exporter.shutdown()


@pytest.mark.unit
def test_app_factory_wires_fastapi_instrumentation(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import main

    calls: list[tuple[str, object]] = []

    class Exporter:
        is_active = True

        def __init__(self, service_name: str, endpoint: str) -> None:
            calls.extend((("service", service_name), ("endpoint", endpoint)))

        def instrument_fastapi(self, app: FastAPI) -> bool:
            calls.append(("app", app))
            return True

        def shutdown(self) -> None:
            pass

    monkeypatch.setattr(main, "OTLPExporter", Exporter)
    app = main.create_app(Settings(otel_endpoint="http://otel-collector:4317"))

    assert ("service", "cogentrex") in calls
    assert ("endpoint", "http://otel-collector:4317") in calls
    assert ("app", app) in calls
    assert isinstance(app.state.otel_exporter, Exporter)
