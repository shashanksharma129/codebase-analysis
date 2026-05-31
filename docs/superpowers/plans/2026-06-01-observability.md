# Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add structured JSON logging and OpenTelemetry distributed tracing to the Codebase Analyzer, emitted to stdout for Cloud Run / Google Cloud Logging.

**Architecture:** A single `src/observability.py` module owns all setup. `setup_telemetry()` configures stdlib logging with a JSON formatter + trace-ID injection, and sets up an OTel `TracerProvider` whose `JsonLogSpanExporter` serialises finished spans as JSON log lines. All other modules just call `logging.getLogger(__name__)` and `trace.get_tracer(__name__)` — zero coupling to the observability implementation.

**Tech Stack:** Python stdlib `logging`, `opentelemetry-api`, `opentelemetry-sdk`. No OTLP endpoint; spans go to stdout via the logging system.

---

## File Map

```
pyproject.toml               add opentelemetry-api, opentelemetry-sdk
src/observability.py         NEW — JsonFormatter, TraceIdFilter, JsonLogSpanExporter, setup_telemetry()
tests/test_observability.py  NEW — 5 unit tests for observability components
src/cache.py                 add logger.debug for cache hit/miss
src/loader.py                add logger.info for domain discovery
src/llm_factory.py           add logger.info for LLM init
src/pipeline.py              add OTel spans + logger.info/warning calls
tests/test_pipeline.py       add one span test using InMemorySpanExporter
src/cli.py                   call setup_telemetry(); replace click.echo with logger.info; add analyze_repo span
ui.py                        call setup_telemetry(); add analyze_repo + download_zip spans; log errors
```

---

### Task 1: Add opentelemetry dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Update pyproject.toml**

Replace the `dependencies` list in `pyproject.toml` with:

```toml
dependencies = [
    "langchain>=0.3",
    "langchain-anthropic>=1.1.0",
    "langchain-openai",
    "langchain-google-genai",
    "pydantic>=2",
    "click",
    "tenacity",
    "streamlit",
    "python-dotenv",
    "requests",
    "opentelemetry-api",
    "opentelemetry-sdk",
]
```

- [ ] **Step 2: Sync dependencies**

```bash
cd /home/shashank_sharma1/code/codebase-analysis && uv sync
```

Expected: resolves and installs `opentelemetry-api` and `opentelemetry-sdk`, updates `uv.lock`.

- [ ] **Step 3: Run full suite to confirm nothing broke**

```bash
cd /home/shashank_sharma1/code/codebase-analysis && uv run pytest -v 2>&1 | tail -5
```

Expected: `37 passed`.

- [ ] **Step 4: Commit**

```bash
cd /home/shashank_sharma1/code/codebase-analysis && git add pyproject.toml uv.lock && git commit -m "chore: add opentelemetry-api and opentelemetry-sdk dependencies"
```

---

### Task 2: Create src/observability.py (TDD)

**Files:**
- Create: `tests/test_observability.py`
- Create: `src/observability.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_observability.py`:

```python
import json
import logging

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from src.observability import JsonFormatter, JsonLogSpanExporter, TraceIdFilter, setup_telemetry


def _make_record(msg: str = "hello", level: int = logging.INFO, name: str = "test.logger") -> logging.LogRecord:
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
        original_configured = obs._telemetry_configured
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
```

- [ ] **Step 2: Run tests to verify FAIL**

```bash
cd /home/shashank_sharma1/code/codebase-analysis && uv run pytest tests/test_observability.py -v 2>&1 | head -15
```

Expected: `ModuleNotFoundError: No module named 'src.observability'`

- [ ] **Step 3: Create src/observability.py**

```python
import atexit
import json
import logging
import sys
from datetime import datetime, timezone
from typing import Sequence

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult

_telemetry_configured = False

_LOG_RECORD_ATTRS = frozenset({
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "message", "taskName",
})


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        record.message = record.getMessage()
        payload: dict = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc)
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
        return json.dumps(payload)


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
                        "name": span.name,
                        "start_time": datetime.fromtimestamp(start_ns / 1e9, tz=timezone.utc)
                        .strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
                        "end_time": datetime.fromtimestamp(end_ns / 1e9, tz=timezone.utc)
                        .strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
                        "duration_ms": duration_ms,
                        "status": span.status.status_code.name,
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
    root.setLevel(logging.DEBUG)
    root.addHandler(handler)


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
    provider = _configure_tracing()
    atexit.register(provider.force_flush)
    _telemetry_configured = True
```

- [ ] **Step 4: Run tests to verify PASS**

```bash
cd /home/shashank_sharma1/code/codebase-analysis && uv run pytest tests/test_observability.py -v
```

Expected: `9 passed` (4 JsonFormatter + 3 TraceIdFilter + 1 JsonLogSpanExporter + 1 SetupTelemetry).

- [ ] **Step 5: Run full suite**

```bash
cd /home/shashank_sharma1/code/codebase-analysis && uv run pytest -v 2>&1 | tail -5
```

Expected: `46 passed` (37 existing + 9 new).

- [ ] **Step 6: Lint**

```bash
cd /home/shashank_sharma1/code/codebase-analysis && uv run ruff check src/observability.py tests/test_observability.py
```

Expected: no issues.

- [ ] **Step 7: Commit**

```bash
cd /home/shashank_sharma1/code/codebase-analysis && git add src/observability.py tests/test_observability.py && git commit -m "feat: add observability module (JSON logging + OTel tracing)"
```

---

### Task 3: Instrument cache.py, loader.py, llm_factory.py

**Files:**
- Modify: `src/cache.py`
- Modify: `src/loader.py`
- Modify: `src/llm_factory.py`

- [ ] **Step 1: Update src/cache.py**

Replace the entire file:

```python
import hashlib
import logging
from pathlib import Path

from src.models import DomainAnalysis

logger = logging.getLogger(__name__)


class DiskCache:
    def __init__(self, cache_dir: Path = Path(".cache")) -> None:
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _key(self, files: list[Path]) -> str:
        content = "".join(p.read_text(errors="ignore") for p in sorted(files))
        return hashlib.sha256(content.encode()).hexdigest()

    def get(self, files: list[Path]) -> DomainAnalysis | None:
        key = self._key(files)
        path = self.cache_dir / f"{key}.json"
        if path.exists():
            logger.debug("Cache hit", extra={"key": key[:8]})
            return DomainAnalysis.model_validate_json(path.read_text())
        logger.debug("Cache miss", extra={"key": key[:8]})
        return None

    def set(self, files: list[Path], analysis: DomainAnalysis) -> None:
        path = self.cache_dir / f"{self._key(files)}.json"
        path.write_text(analysis.model_dump_json(indent=2))
```

- [ ] **Step 2: Update src/loader.py**

Replace the entire file:

```python
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_DOMAIN_MARKERS = frozenset(
    {"services", "modules", "features", "domain", "domains", "packages"}
)
_SKIP_SEGMENTS = frozenset({
    "src", "main", "test", "java", "kotlin", "resources",
    "com", "org", "net", "io", "app", "application",
})


class FileLoader:
    def __init__(self, source: Path, ext: str = ".java") -> None:
        self.source = source
        self.ext = ext

    def load(self) -> dict[str, list[Path]]:
        domains: dict[str, list[Path]] = {}
        for path in sorted(self.source.rglob(f"*{self.ext}")):
            domain = self._domain_for(path)
            domains.setdefault(domain, []).append(path)
        total_files = sum(len(v) for v in domains.values())
        logger.info(
            "Domains discovered",
            extra={"domain_count": len(domains), "total_files": total_files},
        )
        return domains

    def _domain_for(self, path: Path) -> str:
        parts = path.relative_to(self.source).parts[:-1]
        for i, part in enumerate(parts):
            if part in _DOMAIN_MARKERS and i + 1 < len(parts):
                return parts[i + 1]
        for part in parts:
            if part.lower() not in _SKIP_SEGMENTS:
                return part
        return "default"
```

- [ ] **Step 3: Update src/llm_factory.py**

Replace the entire file:

```python
import logging
import os

import click
from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)

_PROVIDER_API_KEYS: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "google_genai": "GOOGLE_API_KEY",
}

_DEFAULT_MODELS: dict[str, str] = {
    "anthropic": "claude-sonnet-4-6",
    "openai": "gpt-4o",
    "google_genai": "gemini-2.5-flash-lite",
}


def create_llm(provider: str | None = None, model: str | None = None) -> BaseChatModel:
    provider = provider or os.environ.get("LLM_PROVIDER", "anthropic")
    model = model or os.environ.get("LLM_MODEL") or _DEFAULT_MODELS.get(provider, "")

    required_key = _PROVIDER_API_KEYS.get(provider)
    if required_key and not os.environ.get(required_key):
        raise click.ClickException(
            f"Provider '{provider}' requires the {required_key} environment variable.\n"
            f"Set it in your shell or copy .env.example to .env and fill it in."
        )

    llm = init_chat_model(f"{provider}:{model}", max_retries=3, temperature=0)
    logger.info("LLM initialized", extra={"provider": provider, "model": model})
    return llm
```

- [ ] **Step 4: Run full suite**

```bash
cd /home/shashank_sharma1/code/codebase-analysis && uv run pytest -v 2>&1 | tail -5
```

Expected: `46 passed`.

- [ ] **Step 5: Lint**

```bash
cd /home/shashank_sharma1/code/codebase-analysis && uv run ruff check src/cache.py src/loader.py src/llm_factory.py
```

Expected: no issues.

- [ ] **Step 6: Commit**

```bash
cd /home/shashank_sharma1/code/codebase-analysis && git add src/cache.py src/loader.py src/llm_factory.py && git commit -m "feat: add structured logging to cache, loader, and llm_factory"
```

---

### Task 4: Instrument src/pipeline.py

**Files:**
- Modify: `src/pipeline.py`
- Modify: `tests/test_pipeline.py`

- [ ] **Step 1: Add a span test to tests/test_pipeline.py**

Add the following test at the bottom of `tests/test_pipeline.py` (after the existing imports, add the new import; after the existing tests, add the new test):

Add to the top-level imports:
```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
```

Add as the final test function:
```python
@pytest.mark.asyncio
async def test_run_pipeline_creates_run_pipeline_span(tmp_path):
    in_memory = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(in_memory))
    original_provider = trace.get_tracer_provider()
    trace.set_tracer_provider(provider)

    f = tmp_path / "src/main/java/services/catalog/Foo.java"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("class Foo {}")

    try:
        with (
            patch("src.pipeline._analyze_domain", new=AsyncMock(return_value=(_make_domain("catalog"), []))),
            patch("src.pipeline._run_aggregation", new=AsyncMock(return_value=_make_report())),
        ):
            await run_pipeline(tmp_path, MagicMock(), cache=None)

        span_names = [s.name for s in in_memory.get_finished_spans()]
        assert "run_pipeline" in span_names
    finally:
        trace.set_tracer_provider(original_provider)
```

- [ ] **Step 2: Run new test to verify FAIL**

```bash
cd /home/shashank_sharma1/code/codebase-analysis && uv run pytest tests/test_pipeline.py::test_run_pipeline_creates_run_pipeline_span -v
```

Expected: FAIL — `AssertionError: assert 'run_pipeline' in []` (no spans emitted yet).

- [ ] **Step 3: Replace src/pipeline.py**

```python
import asyncio
import logging
import time
from pathlib import Path

from langchain_core.language_models import BaseChatModel
from opentelemetry import trace
from opentelemetry.trace import StatusCode

from src.cache import DiskCache
from src.loader import FileLoader
from src.models import DomainAnalysis, FinalOutput, ProjectReport, ProjectSummary
from src.prompts import AGGREGATION_PROMPT, EXTRACTION_PROMPT

_MAX_CHARS_PER_DOMAIN = 80_000

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


def _read_domain(files: list[Path]) -> tuple[str, list[str]]:
    parts: list[str] = []
    skipped: list[str] = []
    total = 0
    for f in sorted(files):
        try:
            content = f.read_text(errors="ignore")
        except OSError:
            skipped.append(str(f))
            logger.warning("Skipped unreadable file", extra={"path": str(f)})
            continue
        header = f"// {f.name}\n"
        chunk_size = len(header) + len(content)
        if total + chunk_size > _MAX_CHARS_PER_DOMAIN:
            remaining = _MAX_CHARS_PER_DOMAIN - total - len(header)
            if remaining > 0:
                parts.append(f"{header}{content[:remaining]}\n// [truncated]")
            break
        parts.append(f"{header}{content}")
        total += chunk_size
    return "\n\n".join(parts), skipped


async def _analyze_domain(
    domain: str,
    files: list[Path],
    llm: BaseChatModel,
    cache: DiskCache | None,
) -> tuple[DomainAnalysis, list[str]]:
    with tracer.start_as_current_span(
        "analyze_domain",
        attributes={"domain": domain, "file_count": len(files)},
    ) as span:
        try:
            t0 = time.monotonic()
            logger.info("Domain analysis started", extra={"domain": domain, "file_count": len(files)})

            if cache:
                cached = cache.get(files)
                if cached:
                    span.set_attribute("cache_hit", True)
                    span.set_attribute("complexity", cached.complexity)
                    logger.info(
                        "Domain analysis complete",
                        extra={
                            "domain": domain,
                            "duration_ms": round((time.monotonic() - t0) * 1000),
                            "complexity": cached.complexity,
                        },
                    )
                    return cached, []

            span.set_attribute("cache_hit", False)
            source, skipped = _read_domain(files)
            chain = EXTRACTION_PROMPT | llm.with_structured_output(DomainAnalysis, method="json_schema")
            result: DomainAnalysis = await chain.ainvoke({
                "domain_name": domain,
                "file_count": len(files),
                "source_code": source,
            })

            if cache:
                cache.set(files, result)

            span.set_attribute("complexity", result.complexity)
            logger.info(
                "Domain analysis complete",
                extra={
                    "domain": domain,
                    "duration_ms": round((time.monotonic() - t0) * 1000),
                    "complexity": result.complexity,
                },
            )
            return result, skipped
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(StatusCode.ERROR)
            raise


async def _run_aggregation(
    domain_results: list[DomainAnalysis],
    llm: BaseChatModel,
) -> ProjectReport:
    with tracer.start_as_current_span(
        "run_aggregation",
        attributes={"domain_count": len(domain_results)},
    ) as span:
        try:
            summaries = "\n\n".join(
                f"=== {d.name} ===\n{d.model_dump_json(indent=2)}" for d in domain_results
            )
            chain = AGGREGATION_PROMPT | llm.with_structured_output(ProjectReport, method="json_schema")
            result = await chain.ainvoke({"domain_summaries": summaries})
            total_methods = sum(len(d.methods) for d in domain_results)
            span.set_attribute("total_methods", total_methods)
            span.set_attribute("overall_complexity", result.summary.overall_complexity)
            logger.info(
                "Aggregation complete",
                extra={
                    "domain_count": len(domain_results),
                    "total_methods": total_methods,
                    "overall_complexity": result.summary.overall_complexity,
                },
            )
            return result
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(StatusCode.ERROR)
            raise


async def run_pipeline(
    source: Path,
    llm: BaseChatModel,
    cache: DiskCache | None,
    ext: str = ".java",
) -> FinalOutput:
    with tracer.start_as_current_span("run_pipeline") as span:
        try:
            loader = FileLoader(source, ext=ext)
            domains = loader.load()

            span.set_attribute("domain_count", len(domains))
            span.set_attribute("total_files", sum(len(f) for f in domains.values()))
            span.set_attribute("ext", ext)

            if not domains:
                report = await _run_aggregation([], llm)
                return FinalOutput(
                    project=report.project,
                    domains=[],
                    summary=ProjectSummary(
                        total_files=0,
                        total_domains=0,
                        total_methods=0,
                        overall_complexity=report.summary.overall_complexity,
                        key_patterns=report.summary.key_patterns,
                        notable_aspects=report.summary.notable_aspects,
                    ),
                )

            tasks = [
                _analyze_domain(name, files, llm, cache)
                for name, files in domains.items()
            ]
            domain_tuples: list[tuple[DomainAnalysis, list[str]]] = list(await asyncio.gather(*tasks))
            domain_results = [d for d, _ in domain_tuples]
            all_skipped = [p for _, skipped in domain_tuples for p in skipped]

            report = await _run_aggregation(domain_results, llm)

            return FinalOutput(
                project=report.project,
                domains=domain_results,
                summary=ProjectSummary(
                    total_files=sum(len(files) for files in domains.values()),
                    total_domains=len(domain_results),
                    total_methods=sum(len(d.methods) for d in domain_results),
                    overall_complexity=report.summary.overall_complexity,
                    key_patterns=report.summary.key_patterns,
                    notable_aspects=report.summary.notable_aspects,
                    skipped_files=all_skipped,
                ),
            )
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(StatusCode.ERROR)
            raise
```

- [ ] **Step 4: Run full suite**

```bash
cd /home/shashank_sharma1/code/codebase-analysis && uv run pytest -v 2>&1 | tail -5
```

Expected: `47 passed` (46 previous + 1 new span test).

- [ ] **Step 5: Lint**

```bash
cd /home/shashank_sharma1/code/codebase-analysis && uv run ruff check src/pipeline.py tests/test_pipeline.py
```

Expected: no issues.

- [ ] **Step 6: Commit**

```bash
cd /home/shashank_sharma1/code/codebase-analysis && git add src/pipeline.py tests/test_pipeline.py && git commit -m "feat: add OTel spans and structured logging to pipeline"
```

---

### Task 5: Update src/cli.py

**Files:**
- Modify: `src/cli.py`

- [ ] **Step 1: Replace src/cli.py**

```python
import asyncio
import logging
import os
import time
from pathlib import Path

import click
from opentelemetry import trace
from opentelemetry.trace import StatusCode

from src.cache import DiskCache
from src.llm_factory import create_llm
from src.observability import setup_telemetry
from src.pipeline import run_pipeline

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


@click.command()
@click.option(
    "--source",
    required=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Path to codebase root to analyze.",
)
@click.option(
    "--output",
    default="output.json",
    show_default=True,
    type=click.Path(path_type=Path),
    help="Output JSON file path.",
)
@click.option(
    "--provider",
    default=None,
    help="LLM provider: anthropic | openai | google_genai (overrides LLM_PROVIDER env var).",
)
@click.option(
    "--model",
    default=None,
    help="Model name (overrides LLM_MODEL env var).",
)
@click.option(
    "--no-cache",
    "no_cache",
    is_flag=True,
    default=False,
    help="Disable disk cache.",
)
@click.option(
    "--ext",
    default=".java",
    show_default=True,
    help="File extension filter.",
)
def analyze(
    source: Path,
    output: Path,
    provider: str | None,
    model: str | None,
    no_cache: bool,
    ext: str,
) -> None:
    """Analyze a codebase and extract structured knowledge to JSON."""
    setup_telemetry()
    llm = create_llm(provider, model)
    cache = None if no_cache else DiskCache()

    resolved_provider = provider or os.environ.get("LLM_PROVIDER", "anthropic")
    with tracer.start_as_current_span(
        "analyze_repo",
        attributes={"repo": str(source), "provider": resolved_provider},
    ) as span:
        try:
            t0 = time.monotonic()
            result = asyncio.run(run_pipeline(source, llm, cache, ext))
            duration_ms = round((time.monotonic() - t0) * 1000)

            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(result.model_dump_json(indent=2, by_alias=True))
            logger.info(
                "Analysis complete",
                extra={"output_path": str(output), "duration_ms": duration_ms},
            )
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(StatusCode.ERROR)
            raise
```

- [ ] **Step 2: Run full suite**

```bash
cd /home/shashank_sharma1/code/codebase-analysis && uv run pytest -v 2>&1 | tail -5
```

Expected: `47 passed`.

- [ ] **Step 3: Lint**

```bash
cd /home/shashank_sharma1/code/codebase-analysis && uv run ruff check src/cli.py
```

Expected: no issues.

- [ ] **Step 4: Commit**

```bash
cd /home/shashank_sharma1/code/codebase-analysis && git add src/cli.py && git commit -m "feat: add OTel span and structured logging to CLI"
```

---

### Task 6: Update ui.py

**Files:**
- Modify: `ui.py`

- [ ] **Step 1: Replace ui.py**

```python
import asyncio
import io
import logging
import os
import re
import shutil
import tempfile
import time
import zipfile
from pathlib import Path

import click
import requests
import streamlit as st
from dotenv import load_dotenv
from opentelemetry import trace
from opentelemetry.trace import StatusCode

from src.cache import DiskCache
from src.llm_factory import create_llm
from src.observability import setup_telemetry
from src.pipeline import run_pipeline

load_dotenv()
setup_telemetry()

st.set_page_config(page_title="Codebase Analyzer", layout="wide")

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

_GITHUB_RE = re.compile(
    r"https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?(?:/tree/([^/]+))?/?$"
)
_COMPLEXITY_BADGE = {"low": "🟢 low", "medium": "🟡 medium", "high": "🔴 high"}


def parse_github_url(url: str) -> tuple[str, str, str]:
    """Returns (owner, repo, branch). Raises ValueError on no match."""
    m = _GITHUB_RE.match(url.strip())
    if not m:
        raise ValueError(f"Not a valid GitHub URL: {url!r}")
    owner, repo, branch = m.group(1), m.group(2), m.group(3) or "main"
    return owner, repo, branch


def _download_and_extract(owner: str, repo: str, branch: str, dest: Path) -> tuple[Path, int]:
    zip_url = f"https://github.com/{owner}/{repo}/archive/refs/heads/{branch}.zip"
    resp = requests.get(zip_url, timeout=60)
    if resp.status_code != 200:
        raise RuntimeError(f"Failed to download repository: HTTP {resp.status_code}")
    zip_bytes = len(resp.content)
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        zf.extractall(dest)
    return next(dest.iterdir()), zip_bytes


# LLM + cache initialised once at startup
try:
    _llm = create_llm()
    _cache = DiskCache()
except click.ClickException as e:
    st.error(e.format_message())
    st.stop()

# ── Page header ───────────────────────────────────────────────────────────────
st.title("Codebase Analyzer")
_provider = os.environ.get("LLM_PROVIDER", "anthropic")
_model = os.environ.get("LLM_MODEL", "")
st.caption(
    f"Provider: **{_provider}**" + (f"  ·  Model: **{_model}**" if _model else "")
)

# ── Input ─────────────────────────────────────────────────────────────────────
col_url, col_branch = st.columns([4, 1])
with col_url:
    url = st.text_input(
        "GitHub Repository URL", placeholder="https://github.com/owner/repo"
    )
with col_branch:
    branch_input = st.text_input("Branch", value="main")

analyze_clicked = st.button("Analyze", type="primary", disabled=not url.strip())

# ── Analysis ──────────────────────────────────────────────────────────────────
if analyze_clicked and url.strip():
    try:
        owner, repo, branch_from_url = parse_github_url(url)
    except ValueError as e:
        st.error(str(e))
        st.stop()

    branch = branch_input.strip() or branch_from_url
    tmp = tempfile.mkdtemp()
    result = None
    error_msg = None

    with tracer.start_as_current_span(
        "analyze_repo",
        attributes={"repo": repo, "branch": branch, "provider": _provider},
    ) as span:
        try:
            with st.status("Downloading repository...", expanded=True) as status:
                with tracer.start_as_current_span(
                    "download_zip",
                    attributes={"repo": repo, "branch": branch},
                ) as dl_span:
                    source, zip_bytes = _download_and_extract(owner, repo, branch, Path(tmp))
                    dl_span.set_attribute("zip_bytes", zip_bytes)
                status.update(label="Analyzing repository...")
                result = asyncio.run(run_pipeline(source, _llm, _cache))
                status.update(label="Done.", state="complete")
            span.set_status(StatusCode.OK)
        except RuntimeError as e:
            error_msg = str(e)
            logger.error(
                "Download failed",
                extra={"repo": repo, "branch": branch, "error": str(e)},
            )
            span.record_exception(e)
            span.set_status(StatusCode.ERROR)
        except requests.RequestException as e:
            error_msg = f"Network error: {e}"
            logger.error(
                "Download failed",
                extra={"repo": repo, "branch": branch, "error": str(e)},
            )
            span.record_exception(e)
            span.set_status(StatusCode.ERROR)
        except Exception as e:
            error_msg = f"Analysis failed: {e}"
            logger.error("Analysis failed", extra={"repo": repo, "error": str(e)})
            span.record_exception(e)
            span.set_status(StatusCode.ERROR)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    if error_msg:
        st.error(error_msg)

    elif result:
        tab_summary, tab_json = st.tabs(["Summary", "Raw JSON"])

        with tab_summary:
            st.subheader(result.project.name)
            st.markdown(result.project.overview)
            st.caption(result.project.purpose)

            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Architecture", result.project.architecture_pattern)
            c2.metric("Complexity", _COMPLEXITY_BADGE[result.summary.overall_complexity])
            c3.metric("Files", result.summary.total_files)
            c4.metric("Domains", result.summary.total_domains)
            c5.metric("Methods", result.summary.total_methods)

            if result.project.tech_stack:
                st.markdown(
                    "**Tech stack:** "
                    + "  ".join(f"`{t}`" for t in result.project.tech_stack)
                )

            if result.domains:
                st.markdown("### Domains")
                cols = st.columns(3)
                for i, domain in enumerate(result.domains):
                    with cols[i % 3]:
                        st.markdown(
                            f"**{domain.name}** — "
                            f"{_COMPLEXITY_BADGE[domain.complexity]}\n\n"
                            f"{domain.file_count} files · {len(domain.methods)} methods\n\n"
                            f"_{domain.description}_"
                        )
            else:
                st.info(
                    "No domains found — no Java files detected in this repository."
                )

        with tab_json:
            st.download_button(
                "Download report.json",
                data=result.model_dump_json(indent=2, by_alias=True),
                file_name=f"{repo}-report.json",
                mime="application/json",
            )
            st.json(result.model_dump(by_alias=True))
```

- [ ] **Step 2: Run full suite**

```bash
cd /home/shashank_sharma1/code/codebase-analysis && uv run pytest -v 2>&1 | tail -5
```

Expected: `47 passed`.

- [ ] **Step 3: Lint**

```bash
cd /home/shashank_sharma1/code/codebase-analysis && uv run ruff check ui.py
```

Expected: no issues.

- [ ] **Step 4: Commit**

```bash
cd /home/shashank_sharma1/code/codebase-analysis && git add ui.py && git commit -m "feat: add OTel spans, structured logging, and download size tracking to UI"
```

---

## Self-Review

**Spec coverage:**
- ✅ `setup_telemetry()` in `src/observability.py` — Task 2
- ✅ `JsonFormatter` with `severity` field, ISO timestamp, extra fields — Task 2
- ✅ `TraceIdFilter` injects `trace_id` from OTel context; preserves existing — Task 2
- ✅ `JsonLogSpanExporter` emits spans as JSON via `logging.getLogger("otel.spans")` — Task 2
- ✅ `BatchSpanProcessor` + `atexit.register(force_flush)` — Task 2
- ✅ `setup_telemetry()` idempotent guard — Task 2
- ✅ `opentelemetry-api`, `opentelemetry-sdk` in `pyproject.toml` — Task 1
- ✅ `src/cache.py` debug logging (hit/miss + key prefix) — Task 3
- ✅ `src/loader.py` info logging (domain_count, total_files) — Task 3
- ✅ `src/llm_factory.py` info logging (provider, model) — Task 3
- ✅ `src/pipeline.py` spans for `run_pipeline`, `_analyze_domain`, `run_aggregation` — Task 4
- ✅ `src/pipeline.py` info/warning logging (started, complete, skipped) — Task 4
- ✅ `src/cli.py` `setup_telemetry()` + `analyze_repo` span + `logger.info` replacing `click.echo` — Task 5
- ✅ `ui.py` `setup_telemetry()` + `analyze_repo` span + `download_zip` span + `logger.error` — Task 6
- ✅ span `StatusCode.ERROR` + `record_exception` on all exceptions — Tasks 4, 5, 6
- ✅ `_download_and_extract` returns `(Path, int)` for `zip_bytes` attribute — Task 6
- ✅ 9 tests in `test_observability.py` — Task 2
- ✅ 1 span test in `test_pipeline.py` — Task 4

**Placeholder scan:** None found.

**Type consistency:**
- `_download_and_extract` returns `tuple[Path, int]` in Task 6 — unpacked as `source, zip_bytes = _download_and_extract(...)` ✅
- `TraceIdFilter.filter` preserves existing `trace_id` when set — consistent with `JsonLogSpanExporter` setting it via `extra={}` ✅
- `setup_telemetry()` idempotency flag `_telemetry_configured` used in both `setup_telemetry()` and `test_idempotent` ✅
