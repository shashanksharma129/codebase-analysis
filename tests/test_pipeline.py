# tests/test_pipeline.py
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from src.models import (
    DomainAnalysis,
    FinalOutput,
    ProjectInfo,
    ProjectReport,
    ProjectSummary,
)
from src.pipeline import _read_domain, run_pipeline


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


def test_read_domain_concatenates_files(tmp_path):
    f1, f2 = tmp_path / "A.java", tmp_path / "B.java"
    f1.write_text("class A {}")
    f2.write_text("class B {}")
    source, skipped = _read_domain([f1, f2])
    assert "class A {}" in source
    assert "class B {}" in source
    assert "A.java" in source
    assert skipped == []


def test_read_domain_truncates_at_limit(tmp_path):
    f = tmp_path / "Big.java"
    f.write_text("x" * 90_000)
    source, _ = _read_domain([f])
    assert len(source) <= 81_000


def test_read_domain_skips_unreadable_files(tmp_path):
    f = tmp_path / "Foo.java"
    f.write_text("class Foo {}")
    source, skipped = _read_domain([f, Path("/nonexistent/Ghost.java")])
    assert "class Foo {}" in source
    assert len(skipped) == 1
    assert "Ghost.java" in skipped[0]


@pytest.mark.asyncio
async def test_run_pipeline_returns_final_output(tmp_path):
    f = tmp_path / "src/main/java/services/catalog/Foo.java"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("class Foo {}")

    domain_tuple = (_make_domain("catalog"), [])
    with (
        patch("src.pipeline._analyze_domain", new=AsyncMock(return_value=domain_tuple)),
        patch("src.pipeline._run_aggregation", new=AsyncMock(return_value=_make_report())),
    ):
        result = await run_pipeline(tmp_path, MagicMock(), cache=None)

    assert isinstance(result, FinalOutput)
    assert len(result.domains) == 1
    assert result.domains[0].name == "catalog"


@pytest.mark.asyncio
async def test_run_pipeline_overrides_numeric_summary(tmp_path):
    f = tmp_path / "src/main/java/services/catalog/Foo.java"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("class Foo {}")

    domain_tuple = (_make_domain("catalog"), [])
    with (
        patch("src.pipeline._analyze_domain", new=AsyncMock(return_value=domain_tuple)),
        patch("src.pipeline._run_aggregation", new=AsyncMock(return_value=_make_report())),
    ):
        result = await run_pipeline(tmp_path, MagicMock(), cache=None)

    assert result.summary.total_domains == 1
    assert result.summary.total_files == 1
    assert result.summary.total_methods == 0


@pytest.mark.asyncio
async def test_run_pipeline_empty_source(tmp_path):
    with patch("src.pipeline._run_aggregation", new=AsyncMock(return_value=_make_report())):
        result = await run_pipeline(tmp_path, MagicMock(), cache=None)

    assert result.domains == []
    assert result.summary.total_domains == 0
    assert result.summary.total_files == 0


@pytest.mark.asyncio
async def test_run_pipeline_collects_skipped_files(tmp_path):
    f = tmp_path / "src/main/java/services/catalog/Foo.java"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("class Foo {}")

    with (
        patch(
            "src.pipeline._analyze_domain",
            new=AsyncMock(return_value=(_make_domain("catalog"), ["/missing/Bar.java"])),
        ),
        patch("src.pipeline._run_aggregation", new=AsyncMock(return_value=_make_report())),
    ):
        result = await run_pipeline(tmp_path, MagicMock(), cache=None)

    assert result.summary.skipped_files == ["/missing/Bar.java"]


@pytest.mark.asyncio
async def test_run_pipeline_creates_run_pipeline_span(tmp_path):
    in_memory = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(in_memory))

    f = tmp_path / "src/main/java/services/catalog/Foo.java"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("class Foo {}")

    with (
        patch("src.pipeline.tracer", provider.get_tracer("src.pipeline")),
        patch(
            "src.pipeline._analyze_domain",
            new=AsyncMock(return_value=(_make_domain("catalog"), [])),
        ),
        patch("src.pipeline._run_aggregation", new=AsyncMock(return_value=_make_report())),
    ):
        await run_pipeline(tmp_path, MagicMock(), cache=None)

    span_names = [s.name for s in in_memory.get_finished_spans()]
    assert "run_pipeline" in span_names
