# tests/test_pipeline.py
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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
    result = _read_domain([f1, f2])
    assert "class A {}" in result
    assert "class B {}" in result
    assert "A.java" in result


def test_read_domain_truncates_at_limit(tmp_path):
    f = tmp_path / "Big.java"
    f.write_text("x" * 90_000)
    result = _read_domain([f])
    assert len(result) <= 81_000


def test_read_domain_skips_unreadable_files(tmp_path):
    f = tmp_path / "Foo.java"
    f.write_text("class Foo {}")
    result = _read_domain([f, Path("/nonexistent/Ghost.java")])
    assert "class Foo {}" in result


@pytest.mark.asyncio
async def test_run_pipeline_returns_final_output(tmp_path):
    f = tmp_path / "src/main/java/services/catalog/Foo.java"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("class Foo {}")

    with (
        patch("src.pipeline._analyze_domain", new=AsyncMock(return_value=_make_domain("catalog"))),
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

    with (
        patch("src.pipeline._analyze_domain", new=AsyncMock(return_value=_make_domain("catalog"))),
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
