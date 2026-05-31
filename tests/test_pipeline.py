from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from src.models import (
    DomainAnalysis,
    FinalOutput,
    ProjectInfo,
    ProjectReport,
    ProjectSummary,
)
from src.pipeline import _run_aggregation, run_pipeline


def _make_domain(name: str = "catalog") -> DomainAnalysis:
    return DomainAnalysis(
        name=name,
        description="d",
        file_count=1,
        complexity="low",
        methods=[],
        notable_aspects=[],
    )


def _make_report() -> ProjectReport:
    return ProjectReport(
        project=ProjectInfo(
            name="test-project",
            overview="A test project",
            purpose="Testing",
            tech_stack=["Spring Boot"],
            architecture_pattern="MVC",
        ),
        summary=ProjectSummary(
            total_files=0,
            total_domains=0,
            total_methods=0,
            overall_complexity="low",
            key_patterns=["Repository pattern"],
            notable_aspects=["JWT auth"],
        ),
    )


def _make_mock_analyzer(domain_map=None, domain_return=None, ext=".java"):
    from src.prompts import AGGREGATION_PROMPT
    mock = MagicMock()
    mock.ext = ext
    mock.get_domain_map.return_value = domain_map or {}
    mock.analyze_domain = AsyncMock(return_value=(domain_return or (_make_domain(), [])))
    mock.get_aggregation_prompt.return_value = AGGREGATION_PROMPT
    return mock


@pytest.mark.asyncio
async def test_run_pipeline_returns_final_output(tmp_path):
    f = tmp_path / "src/main/java/services/catalog/Foo.java"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("class Foo {}")

    analyzer = _make_mock_analyzer(
        domain_map={"catalog": [f]},
        domain_return=(_make_domain("catalog"), []),
    )
    with patch("src.pipeline._run_aggregation", new=AsyncMock(return_value=_make_report())):
        result = await run_pipeline(tmp_path, MagicMock(), cache=None, analyzer=analyzer)

    assert isinstance(result, FinalOutput)
    assert len(result.domains) == 1
    assert result.domains[0].name == "catalog"


@pytest.mark.asyncio
async def test_run_pipeline_overrides_numeric_summary(tmp_path):
    f = tmp_path / "src/main/java/services/catalog/Foo.java"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("class Foo {}")

    analyzer = _make_mock_analyzer(
        domain_map={"catalog": [f]},
        domain_return=(_make_domain("catalog"), []),
    )
    with patch("src.pipeline._run_aggregation", new=AsyncMock(return_value=_make_report())):
        result = await run_pipeline(tmp_path, MagicMock(), cache=None, analyzer=analyzer)

    assert result.summary.total_domains == 1
    assert result.summary.total_files == 1
    assert result.summary.total_methods == 0


@pytest.mark.asyncio
async def test_run_pipeline_empty_source(tmp_path):
    analyzer = _make_mock_analyzer(domain_map={})
    with patch("src.pipeline._run_aggregation", new=AsyncMock(return_value=_make_report())):
        result = await run_pipeline(tmp_path, MagicMock(), cache=None, analyzer=analyzer)

    assert result.domains == []
    assert result.summary.total_domains == 0
    assert result.summary.total_files == 0


@pytest.mark.asyncio
async def test_run_pipeline_collects_skipped_files(tmp_path):
    f = tmp_path / "src/main/java/services/catalog/Foo.java"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("class Foo {}")

    analyzer = _make_mock_analyzer(
        domain_map={"catalog": [f]},
        domain_return=(_make_domain("catalog"), ["/missing/Bar.java"]),
    )
    with patch("src.pipeline._run_aggregation", new=AsyncMock(return_value=_make_report())):
        result = await run_pipeline(tmp_path, MagicMock(), cache=None, analyzer=analyzer)

    assert result.summary.skipped_files == ["/missing/Bar.java"]


@pytest.mark.asyncio
async def test_run_pipeline_creates_run_pipeline_span(tmp_path):
    in_memory = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(in_memory))

    f = tmp_path / "src/main/java/services/catalog/Foo.java"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("class Foo {}")

    analyzer = _make_mock_analyzer(
        domain_map={"catalog": [f]},
        domain_return=(_make_domain("catalog"), []),
    )
    with (
        patch("src.pipeline.tracer", provider.get_tracer("src.pipeline")),
        patch("src.pipeline._run_aggregation", new=AsyncMock(return_value=_make_report())),
    ):
        await run_pipeline(tmp_path, MagicMock(), cache=None, analyzer=analyzer)

    provider.shutdown()
    span_names = [s.name for s in in_memory.get_finished_spans()]
    assert "run_pipeline" in span_names
    run_pipeline_span = next(s for s in in_memory.get_finished_spans() if s.name == "run_pipeline")
    assert run_pipeline_span.attributes["domain_count"] == 1
    assert run_pipeline_span.status.status_code != StatusCode.ERROR


@pytest.mark.asyncio
async def test_run_pipeline_language_field_java(tmp_path):
    analyzer = _make_mock_analyzer(domain_map={}, ext=".java")
    with patch("src.pipeline._run_aggregation", new=AsyncMock(return_value=_make_report())):
        result = await run_pipeline(tmp_path, MagicMock(), cache=None, analyzer=analyzer)
    assert result.language == "java"


@pytest.mark.asyncio
async def test_run_pipeline_language_field_python(tmp_path):
    analyzer = _make_mock_analyzer(domain_map={}, ext=".py")
    with patch("src.pipeline._run_aggregation", new=AsyncMock(return_value=_make_report())):
        result = await run_pipeline(tmp_path, MagicMock(), cache=None, analyzer=analyzer)
    assert result.language == "py"
