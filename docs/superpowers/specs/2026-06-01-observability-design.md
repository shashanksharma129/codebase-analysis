# Codebase Analyzer — Observability Design Spec

**Date:** 2026-06-01
**Status:** Approved

---

## Overview

Add full observability to the Codebase Analyzer: structured JSON logging and OpenTelemetry distributed tracing, both emitted to stdout. Designed for Cloud Run, where stdout is automatically captured by Google Cloud Logging.

No dedicated tracing backend is required. Traces are serialized as JSON log lines alongside regular log entries — one stdout stream, zero extra infrastructure, free tier compatible.

**Invocation (unchanged):**
```bash
streamlit run ui.py          # UI
uv run python main.py ...    # CLI
```

---

## New Files & Changes

| File | Action | Description |
|---|---|---|
| `src/observability.py` | Create | `setup_telemetry()`, `JsonLogSpanExporter`, `TraceIdFilter`, JSON formatter |
| `tests/test_observability.py` | Create | Unit tests for all observability components |
| `src/pipeline.py` | Modify | Add spans + structured log calls |
| `src/cache.py` | Modify | Add debug log for cache hit/miss |
| `src/loader.py` | Modify | Add info log for domain discovery |
| `src/llm_factory.py` | Modify | Add info log for LLM initialization |
| `ui.py` | Modify | Call `setup_telemetry()`; add `analyze_repo` + `download_zip` spans; log errors |
| `src/cli.py` | Modify | Call `setup_telemetry()`; replace `click.echo` with `logger.info`; add `analyze_repo` span |
| `pyproject.toml` | Modify | Add `opentelemetry-api`, `opentelemetry-sdk` |

No changes to `src/prompts.py`, `src/models.py`, or `main.py`.

---

## Dependencies

| Package | Role |
|---|---|
| `opentelemetry-api` | Tracer API, span context, propagation |
| `opentelemetry-sdk` | SDK: `TracerProvider`, `BatchSpanProcessor`, `SpanExporter` base |

Added to `[project].dependencies` in `pyproject.toml`.

---

## Architecture

```
App startup
  └── setup_telemetry()
        ├── stdlib logging
        │     ├── JsonFormatter  → JSON to stdout
        │     └── TraceIdFilter  → injects trace_id into every record
        └── OTel TracerProvider
              └── BatchSpanProcessor
                    └── JsonLogSpanExporter → spans as JSON via logging

One analysis run
  └── Span: analyze_repo        (trace_id: abc123)
        ├── Span: download_zip              [ui.py only]
        └── Span: run_pipeline
              ├── Span: analyze_domain "catalog"   ─┐
              ├── Span: analyze_domain "services"   ├─ concurrent
              ├── Span: analyze_domain "models"    ─┘
              └── Span: run_aggregation
```

`setup_telemetry()` is called once at startup in `ui.py` and `src/cli.py`. All other modules call `logging.getLogger(__name__)` and `get_tracer(__name__)` — they have no dependency on the observability implementation.

---

## Structured Logging

### JSON Log Record Shape

```json
{
  "timestamp": "2026-06-01T10:23:41.123Z",
  "severity": "INFO",
  "logger": "src.pipeline",
  "message": "Domain analysis complete",
  "trace_id": "abc123def456abc123def456abc123de",
  "domain": "catalog",
  "file_count": 12,
  "duration_ms": 3420
}
```

### Field Decisions

- **`severity`** (not `level`) — Cloud Logging parses this field name specifically to classify entries into its severity dropdown, alert policies, and log-based metrics.
- **`trace_id`** — injected automatically by `TraceIdFilter` from the active OTel span context. Empty string `""` when no span is active.
- **`timestamp`** — ISO 8601 UTC, millisecond precision.
- **Extra fields** — callers pass context via `extra={"domain": name, "duration_ms": elapsed}`.

### TraceIdFilter

```python
class TraceIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        span = trace.get_current_span()
        ctx = span.get_span_context()
        record.trace_id = format(ctx.trace_id, "032x") if ctx.is_valid else ""
        return True
```

### Log Events by Module

| Module | Level | Message | Extra fields |
|---|---|---|---|
| `src/llm_factory.py` | INFO | LLM initialized | `provider`, `model` |
| `src/loader.py` | INFO | Domains discovered | `domain_count`, `total_files` |
| `src/cache.py` | DEBUG | Cache hit | `domain`, `key` |
| `src/cache.py` | DEBUG | Cache miss | `domain`, `key` |
| `src/pipeline.py` | INFO | Domain analysis started | `domain`, `file_count` |
| `src/pipeline.py` | INFO | Domain analysis complete | `domain`, `duration_ms`, `complexity` |
| `src/pipeline.py` | WARNING | Skipped unreadable file | `path` |
| `src/pipeline.py` | INFO | Aggregation complete | `domain_count`, `total_methods`, `overall_complexity` |
| `src/cli.py` | INFO | Analysis complete | `output_path`, `duration_ms` |
| `ui.py` | ERROR | Download failed | `repo`, `branch`, `status_code` or `error` |
| `ui.py` | ERROR | Analysis failed | `repo`, `error` |

### Setup

```python
def _configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(TraceIdFilter())
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(handler)
```

`setup_telemetry()` calls `_configure_logging()` first, then `_configure_tracing()`. Calling `setup_telemetry()` a second time is a no-op (guarded by a module-level flag).

---

## OpenTelemetry Tracing

### JsonLogSpanExporter

Serializes finished spans as JSON and emits them via `logging.getLogger("otel.spans")` at DEBUG level. Spans appear in Cloud Logging as structured entries alongside regular log lines, correlated by `trace_id`.

```json
{
  "timestamp": "2026-06-01T10:23:41.123Z",
  "severity": "DEBUG",
  "logger": "otel.spans",
  "message": "span",
  "trace_id": "abc123def456abc123def456abc123de",
  "span_id": "def456abc123def4",
  "parent_span_id": "789abc123def7890",
  "name": "analyze_domain",
  "start_time": "2026-06-01T10:23:38.000Z",
  "end_time": "2026-06-01T10:23:41.123Z",
  "duration_ms": 3123,
  "status": "OK",
  "attributes": {
    "domain": "catalog",
    "file_count": 12,
    "cache_hit": false,
    "complexity": "medium"
  }
}
```

### Span Attributes

| Span | Attributes |
|---|---|
| `analyze_repo` | `repo`, `branch`, `provider` |
| `download_zip` | `repo`, `branch`, `zip_bytes` |
| `run_pipeline` | `domain_count`, `total_files`, `ext` |
| `analyze_domain` | `domain`, `file_count`, `cache_hit`, `complexity` |
| `run_aggregation` | `domain_count`, `total_methods`, `overall_complexity` |

### Span Status

- `StatusCode.OK` on success.
- `StatusCode.ERROR` + `span.record_exception(exc)` on any exception — records the exception type and message as a span event.

### Processor

`BatchSpanProcessor` with default settings. On Cloud Run container shutdown (SIGTERM), `force_flush()` drains the queue before exit so no spans are lost.

### Setup

```python
def _configure_tracing() -> None:
    exporter = JsonLogSpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
```

---

## Integration Details

### ui.py

```python
setup_telemetry()   # called before st.set_page_config

# Around the full analysis block:
tracer = get_tracer(__name__)
with tracer.start_as_current_span("analyze_repo",
        attributes={"repo": repo, "branch": branch, "provider": _provider}):
    with tracer.start_as_current_span("download_zip"):
        source = _download_and_extract(...)
    result = asyncio.run(run_pipeline(...))
```

Errors caught in the except block call both `logger.error(...)` and `st.error(...)`.

### src/cli.py

```python
setup_telemetry()   # called at top of analyze()

tracer = get_tracer(__name__)
with tracer.start_as_current_span("analyze_repo",
        attributes={"repo": str(source), "provider": provider}):
    result = asyncio.run(run_pipeline(...))
```

The two existing `click.echo()` calls are replaced with `logger.info()`.

### src/pipeline.py

`run_pipeline`, `_analyze_domain`, and `_run_aggregation` each open a span with `tracer.start_as_current_span(...)`. OTel's context propagation automatically threads the trace context through `asyncio.gather` — child spans in concurrent domain tasks correctly reference the parent `run_pipeline` span.

---

## Error Handling

| Scenario | Behavior |
|---|---|
| `setup_telemetry()` called twice | No-op; returns immediately |
| Exception inside a span | `span.record_exception(exc)`, `span.set_status(ERROR)`, re-raise |
| `JsonLogSpanExporter.export()` fails | Logs warning to stderr, returns `SpanExportResult.FAILURE`; does not affect analysis |
| No active span (e.g. in tests) | `TraceIdFilter` sets `trace_id = ""`; no crash |

---

## Testing

`tests/test_observability.py` covers:

1. **`JsonFormatter`** — output is valid JSON; contains `severity`, `timestamp`, `logger`, `message`, `trace_id` fields; uses `severity` not `level`.
2. **`TraceIdFilter` with active span** — `trace_id` matches the current span's trace ID.
3. **`TraceIdFilter` without active span** — `trace_id` is `""`.
4. **`JsonLogSpanExporter`** — emitting a finished test span produces one JSON log line with `name`, `trace_id`, `duration_ms`, `status`, `attributes`.
5. **`setup_telemetry()` idempotency** — calling twice does not add duplicate log handlers.

---

## Constraints

- **stdout only** — no file handlers, no Cloud Logging client library, no OTLP HTTP/gRPC endpoint.
- **No changes to `src/models.py` or `src/prompts.py`** — pure data modules stay untouched.
- **`main.py` unchanged** — it delegates to `src/cli.py` which calls `setup_telemetry()`.
- **Test isolation** — `setup_telemetry()` idempotency guard ensures tests that call it don't pollute each other's log handlers.
