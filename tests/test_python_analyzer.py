from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.analyzers.python import PythonAnalyzer
from src.ast_utils import ASTSummary, FileSummary, MethodSummary
from src.models import DomainAnalysis, MethodInfo


def _make_domain(name: str = "api") -> DomainAnalysis:
    return DomainAnalysis(
        name=name, description="d", file_count=1,
        complexity="low", methods=[], notable_aspects=[],
    )


@pytest.fixture(autouse=True)
def reset_graph():
    PythonAnalyzer._graph = None
    yield
    PythonAnalyzer._graph = None


def test_ext():
    assert PythonAnalyzer().ext == ".py"


def test_get_aggregation_prompt_is_python_prompt():
    from src.analyzers.python import PYTHON_AGGREGATION_PROMPT
    assert PythonAnalyzer().get_aggregation_prompt() is PYTHON_AGGREGATION_PROMPT


def test_get_domain_map_package_based(tmp_path):
    (tmp_path / "api" / "__init__.py").parent.mkdir(parents=True)
    (tmp_path / "api" / "__init__.py").write_text("")
    (tmp_path / "api" / "routes.py").write_text("")
    (tmp_path / "services" / "__init__.py").parent.mkdir(parents=True)
    (tmp_path / "services" / "__init__.py").write_text("")
    (tmp_path / "services" / "user.py").write_text("")

    domain_map = PythonAnalyzer().get_domain_map(tmp_path)
    assert "api" in domain_map
    assert "services" in domain_map
    assert any(p.name == "routes.py" for p in domain_map["api"])
    assert any(p.name == "user.py" for p in domain_map["services"])


def test_get_domain_map_falls_back_to_file_loader(tmp_path):
    f = tmp_path / "src/main/python/services/catalog/foo.py"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("class Foo: pass")

    domain_map = PythonAnalyzer().get_domain_map(tmp_path)
    assert len(domain_map) > 0


def test_get_domain_map_skips_pycache(tmp_path):
    (tmp_path / "api" / "__init__.py").parent.mkdir(parents=True)
    (tmp_path / "api" / "__init__.py").write_text("")
    (tmp_path / "api" / "__pycache__").mkdir()
    (tmp_path / "api" / "__pycache__" / "cache.pyc").write_bytes(b"")

    domain_map = PythonAnalyzer().get_domain_map(tmp_path)
    all_files = [p for files in domain_map.values() for p in files]
    assert not any("__pycache__" in str(p) for p in all_files)


@pytest.mark.asyncio
async def test_analyze_domain_cache_hit(tmp_path):
    f = tmp_path / "svc.py"
    f.write_text("class Svc: pass")

    cached = _make_domain()
    mock_cache = MagicMock()
    mock_cache.get.return_value = cached

    result, skipped = await PythonAnalyzer().analyze_domain("api", [f], MagicMock(), mock_cache)
    assert result is cached
    assert skipped == []


@pytest.mark.asyncio
async def test_analyze_domain_graph_succeeds(tmp_path):
    f = tmp_path / "svc.py"
    f.write_text("class Svc:\n    def get(self): pass\n")

    expected = _make_domain()
    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value = AsyncMock(return_value=expected)

    result, skipped = await PythonAnalyzer().analyze_domain("api", [f], mock_llm, None)
    assert isinstance(result, DomainAnalysis)


@pytest.mark.asyncio
async def test_analyze_domain_graph_retry_on_validation_failure(tmp_path):
    f = tmp_path / "svc.py"
    f.write_text("class Svc:\n    def get_user(self): pass\n    def create_user(self): pass\n")

    bad_result = DomainAnalysis(
        name="api", description="d", file_count=1, complexity="low",
        methods=[],
        notable_aspects=[],
    )
    good_result = DomainAnalysis(
        name="api", description="d", file_count=1, complexity="low",
        methods=[
            MethodInfo(class_name="Svc", method_name="get_user", signature="def get_user(self)",
                       description="gets user", http_method=None, endpoint=None, complexity="low"),
            MethodInfo(class_name="Svc", method_name="create_user", signature="def create_user(self)",
                       description="creates user", http_method=None, endpoint=None, complexity="low"),
        ],
        notable_aspects=[],
    )

    mock_llm = MagicMock()
    mock_structured = AsyncMock(side_effect=[bad_result, good_result])
    mock_llm.with_structured_output.return_value = mock_structured

    result, skipped = await PythonAnalyzer().analyze_domain("api", [f], mock_llm, None)
    assert mock_structured.call_count == 2
    assert len(result.methods) == 2


@pytest.mark.asyncio
async def test_analyze_domain_max_retries_exhausted(tmp_path):
    f = tmp_path / "svc.py"
    f.write_text("class Svc:\n    def get(self): pass\n")

    bad_result = DomainAnalysis(
        name="api", description="d", file_count=1,
        complexity="low", methods=[], notable_aspects=[],
    )

    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value = AsyncMock(return_value=bad_result)

    result, _ = await PythonAnalyzer().analyze_domain("api", [f], mock_llm, None)
    assert isinstance(result, DomainAnalysis)


@pytest.mark.asyncio
async def test_web_service_uses_web_prompt(tmp_path):
    f = tmp_path / "router.py"
    f.write_text("from fastapi import FastAPI\napp = FastAPI()\n")

    expected = _make_domain()
    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value = AsyncMock(return_value=expected)

    result, _ = await PythonAnalyzer().analyze_domain("api", [f], mock_llm, None)
    assert isinstance(result, DomainAnalysis)
