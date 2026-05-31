from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from src.analyzers.java import JavaAnalyzer
from src.models import DomainAnalysis


def _make_domain() -> DomainAnalysis:
    return DomainAnalysis(
        name="catalog", description="d", file_count=1,
        complexity="low", methods=[], notable_aspects=[],
    )


def test_ext():
    assert JavaAnalyzer().ext == ".java"


def test_get_domain_map_delegates_to_file_loader(tmp_path):
    f = tmp_path / "src/main/java/services/catalog/Foo.java"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("class Foo {}")

    analyzer = JavaAnalyzer()
    domain_map = analyzer.get_domain_map(tmp_path)
    assert "catalog" in domain_map
    assert f in domain_map["catalog"]


def test_get_aggregation_prompt_returns_java_prompt():
    from src.prompts import AGGREGATION_PROMPT
    analyzer = JavaAnalyzer()
    assert analyzer.get_aggregation_prompt() is AGGREGATION_PROMPT


@pytest.mark.asyncio
async def test_analyze_domain_uses_extraction_prompt(tmp_path):
    f = tmp_path / "Foo.java"
    f.write_text("class Foo {}")

    mock_llm = MagicMock()
    mock_chain = AsyncMock(return_value=_make_domain())
    mock_llm.with_structured_output.return_value = MagicMock()

    with patch("src.analyzers.java.EXTRACTION_PROMPT") as mock_prompt:
        mock_prompt.__or__ = MagicMock(return_value=MagicMock(ainvoke=mock_chain))
        result, skipped = await JavaAnalyzer().analyze_domain("catalog", [f], mock_llm, None)

    assert mock_prompt.__or__.called
    assert skipped == []


@pytest.mark.asyncio
async def test_analyze_domain_cache_hit(tmp_path):
    f = tmp_path / "Foo.java"
    f.write_text("class Foo {}")

    cached = _make_domain()
    mock_cache = MagicMock()
    mock_cache.get.return_value = cached

    result, skipped = await JavaAnalyzer().analyze_domain("catalog", [f], MagicMock(), mock_cache)
    assert result is cached
    assert skipped == []


@pytest.mark.asyncio
async def test_analyze_domain_creates_span(tmp_path):
    f = tmp_path / "Foo.java"
    f.write_text("class Foo {}")

    in_memory = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(in_memory))

    domain_result = _make_domain()
    mock_llm = MagicMock()
    mock_chain = AsyncMock(return_value=domain_result)

    with patch("src.analyzers.java.tracer", provider.get_tracer("test")):
        with patch("src.analyzers.java.EXTRACTION_PROMPT") as mock_prompt:
            mock_prompt.__or__ = MagicMock(return_value=MagicMock(ainvoke=mock_chain))
            await JavaAnalyzer().analyze_domain("catalog", [f], mock_llm, None)

    provider.shutdown()
    span_names = [s.name for s in in_memory.get_finished_spans()]
    assert "analyze_domain" in span_names
