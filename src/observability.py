import json
import logging
import sys
from collections.abc import Sequence
from datetime import UTC, datetime

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult

_telemetry_configured = False

_LOG_RECORD_ATTRS = frozenset({
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "message", "taskName", "asctime",
})


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        record.message = record.getMessage()
        payload: dict = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC)
            .strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "severity": record.levelname,
            "logger": record.name,
            "message": record.message,
            "trace_id": getattr(record, "trace_id", ""),
        }
        for key, value in record.__dict__.items():
            if key not in _LOG_RECORD_ATTRS and key not in payload and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class TraceIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if getattr(record, "trace_id", None):
            return True
        span = trace.get_current_span()
        ctx = span.get_span_context()
        record.trace_id = format(ctx.trace_id, "032x") if ctx.is_valid else ""
        return True


class JsonLogSpanExporter(SpanExporter):
    def __init__(self) -> None:
        self._logger = logging.getLogger("otel.spans")

    def export(self, spans: Sequence) -> SpanExportResult:
        try:
            for span in spans:
                ctx = span.get_span_context()
                parent_id = (
                    format(span.parent.span_id, "016x")
                    if span.parent and span.parent.is_valid
                    else ""
                )
                start_ns = span.start_time or 0
                end_ns = span.end_time or 0
                duration_ms = round((end_ns - start_ns) / 1_000_000, 3) if end_ns > start_ns else 0
                self._logger.debug(
                    "span",
                    extra={
                        "trace_id": format(ctx.trace_id, "032x"),
                        "span_id": format(ctx.span_id, "016x"),
                        "parent_span_id": parent_id,
                        "span_name": span.name,
                        "start_time": datetime.fromtimestamp(start_ns / 1e9, tz=UTC)
                        .strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
                        "end_time": datetime.fromtimestamp(end_ns / 1e9, tz=UTC)
                        .strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
                        "duration_ms": duration_ms,
                        "status": (
                            span.status.status_code.name
                            if span.status.status_code.name != "UNSET"
                            else "OK"
                        ),
                        "attributes": dict(span.attributes or {}),
                    },
                )
            return SpanExportResult.SUCCESS
        except Exception:
            return SpanExportResult.FAILURE

    def shutdown(self) -> None:
        pass


def _configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(TraceIdFilter())
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.setLevel(logging.WARNING)
    root.addHandler(handler)
    for name in ("src", "ui", "otel.spans"):
        logging.getLogger(name).setLevel(logging.DEBUG)


def _configure_tracing() -> TracerProvider:
    exporter = JsonLogSpanExporter()
    provider = TracerProvider(resource=Resource.create({"service.name": "codebase-analyzer"}))
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    return provider


def setup_telemetry() -> None:
    global _telemetry_configured
    if _telemetry_configured:
        return
    _configure_logging()
    _configure_tracing()
    _telemetry_configured = True
