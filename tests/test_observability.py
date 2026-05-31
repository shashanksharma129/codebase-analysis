import json
import logging

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from src.observability import JsonFormatter, JsonLogSpanExporter, TraceIdFilter


def _make_record(
    msg: str = "hello", level: int = logging.INFO, name: str = "test.logger"
) -> logging.LogRecord:
    record = logging.LogRecord(
        name=name, level=level, pathname="test.py", lineno=0,
        msg=msg, args=(), exc_info=None,
    )
    record.trace_id = ""
    return record


class TestJsonFormatter:
    def test_output_is_valid_json(self):
        record = _make_record()
        output = JsonFormatter().format(record)
        assert isinstance(json.loads(output), dict)

    def test_required_fields_present(self):
        record = _make_record()
        output = json.loads(JsonFormatter().format(record))
        for field in ("severity", "timestamp", "logger", "message", "trace_id"):
            assert field in output, f"missing field: {field}"

    def test_uses_severity_not_level(self):
        record = _make_record()
        output = json.loads(JsonFormatter().format(record))
        assert "severity" in output
        assert "level" not in output

    def test_extra_fields_included(self):
        record = _make_record()
        record.domain = "catalog"
        record.file_count = 5
        output = json.loads(JsonFormatter().format(record))
        assert output["domain"] == "catalog"
        assert output["file_count"] == 5


class TestTraceIdFilter:
    def test_injects_trace_id_with_active_span(self):
        provider = TracerProvider()
        tracer = provider.get_tracer("test")
        with tracer.start_as_current_span("test-span") as span:
            record = _make_record()
            TraceIdFilter().filter(record)
            expected = format(span.get_span_context().trace_id, "032x")
            assert record.trace_id == expected

    def test_empty_string_without_active_span(self):
        record = _make_record()
        TraceIdFilter().filter(record)
        assert record.trace_id == ""

    def test_does_not_overwrite_existing_trace_id(self):
        record = _make_record()
        record.trace_id = "preexisting"
        TraceIdFilter().filter(record)
        assert record.trace_id == "preexisting"


class TestJsonLogSpanExporter:
    def test_exports_span_with_required_fields(self, caplog):
        in_memory = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(in_memory))
        tracer = provider.get_tracer("test")

        with tracer.start_as_current_span("my-span", attributes={"domain": "catalog"}):
            pass

        finished = in_memory.get_finished_spans()
        assert len(finished) == 1

        exporter = JsonLogSpanExporter()
        with caplog.at_level(logging.DEBUG, logger="otel.spans"):
            exporter.export(finished)

        span_records = [r for r in caplog.records if r.name == "otel.spans"]
        assert len(span_records) == 1
        r = span_records[0]
        for field in ("trace_id", "span_id", "name", "duration_ms", "status", "attributes"):
            assert hasattr(r, field), f"missing span field: {field}"
        assert r.name == "otel.spans"
        assert getattr(r, "status") == "OK"
        assert getattr(r, "attributes") == {"domain": "catalog"}


class TestSetupTelemetry:
    def test_idempotent(self, monkeypatch):
        import src.observability as obs
        original_provider = trace.get_tracer_provider()
        root = logging.getLogger()
        handlers_snapshot = list(root.handlers)

        try:
            monkeypatch.setattr(obs, "_telemetry_configured", False)
            obs.setup_telemetry()
            count_after_first = len(root.handlers)
            obs.setup_telemetry()
            assert len(root.handlers) == count_after_first
        finally:
            for h in root.handlers[len(handlers_snapshot):]:
                root.removeHandler(h)
            trace.set_tracer_provider(original_provider)
