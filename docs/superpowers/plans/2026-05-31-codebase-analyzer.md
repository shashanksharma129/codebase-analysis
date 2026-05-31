# Codebase Analyzer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a generic Python CLI tool that analyzes any Java codebase hierarchically via LangChain LCEL and emits a structured `output.json`.

**Architecture:** `init_chat_model` factory drives a two-stage LCEL pipeline — concurrent per-domain extraction via `asyncio.gather`, followed by a single aggregation pass over domain summaries only (not raw code). SHA256 disk cache in `.cache/` skips re-analysis of unchanged domains.

**Tech Stack:** Python 3.13, uv, ruff, LangChain ≥0.3, langchain-anthropic ≥1.1.0, langchain-openai, langchain-google-genai, Pydantic v2, Click, pytest + pytest-asyncio, Docker.

---

## File Map

```
src/
  __init__.py          empty package marker
  models.py            Pydantic v2 schemas: MethodInfo, DomainAnalysis, ProjectInfo,
                       ProjectSummary, ProjectReport, FinalOutput
  loader.py            FileLoader: walks source tree, groups files by domain
  cache.py             DiskCache: SHA256-keyed JSON cache in .cache/
  llm_factory.py       create_llm(): init_chat_model wrapper with env validation
  prompts.py           EXTRACTION_PROMPT, AGGREGATION_PROMPT
  pipeline.py          run_pipeline(), _analyze_domain(), _run_aggregation(), _read_domain()
  cli.py               Click CLI (analyze command)
tests/
  __init__.py
  test_models.py
  test_loader.py
  test_cache.py
  test_pipeline.py
main.py                from src.cli import analyze; analyze()
pyproject.toml         uv deps, ruff config, pytest config
.gitignore
Dockerfile             multi-stage: python:3.13-slim + uv
docker-compose.yml
.env.example
README.md
```

---

### Task 1: Bootstrap project

**Files:**
- Modify: `pyproject.toml`
- Create: `src/__init__.py`
- Modify: `main.py`
- Modify: `.gitignore`

- [ ] **Step 1: Replace pyproject.toml**

```toml
[project]
name = "codebase-analysis"
version = "0.1.0"
description = "Generic codebase analyzer using LangChain LCEL + LLM"
readme = "README.md"
requires-python = ">=3.13"
dependencies = [
    "langchain>=0.3",
    "langchain-anthropic>=1.1.0",
    "langchain-openai",
    "langchain-google-genai",
    "pydantic>=2",
    "click",
]

[dependency-groups]
dev = [
    "pytest",
    "pytest-asyncio",
    "ruff",
]

[tool.ruff]
line-length = 100
target-version = "py313"

[tool.ruff.lint]
select = ["E", "F", "I", "UP"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
pythonpath = ["."]
```

- [ ] **Step 2: Install dependencies**

```bash
uv sync
```

Expected: resolves all packages, creates/updates `uv.lock`.

- [ ] **Step 3: Create src/__init__.py**

Empty file — just create it:
```bash
touch src/__init__.py
```

- [ ] **Step 4: Update main.py**

```python
from src.cli import analyze

if __name__ == "__main__":
    analyze()
```

- [ ] **Step 5: Update .gitignore**

Add these lines:
```
.cache/
output/
.env
__pycache__/
*.pyc
.venv/
```

- [ ] **Step 6: Verify ruff runs**

```bash
uv run ruff check src/ main.py
```

Expected: no output (no issues).

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock src/__init__.py main.py .gitignore
git commit -m "chore: bootstrap project with uv, ruff, pytest"
```

---

### Task 2: Pydantic models

**Files:**
- Create: `src/models.py`
- Create: `tests/__init__.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: Create tests/__init__.py**

```bash
touch tests/__init__.py
```

- [ ] **Step 2: Write failing tests**

```python
# tests/test_models.py
import pytest
from pydantic import ValidationError

from src.models import (
    DomainAnalysis,
    FinalOutput,
    MethodInfo,
    ProjectInfo,
    ProjectReport,
    ProjectSummary,
)


def _method(**overrides) -> dict:
    return {
        "class_name": "ActorController",
        "method_name": "getActor",
        "signature": "ResponseEntity<ActorDto> getActor(Integer id)",
        "description": "Fetches actor by ID",
        "http_method": "GET",
        "endpoint": "/api/v1/actors/{id}",
        "complexity": "low",
        **overrides,
    }


def test_method_info_valid():
    m = MethodInfo(**_method())
    assert m.class_name == "ActorController"
    assert m.http_method == "GET"
    assert m.endpoint == "/api/v1/actors/{id}"


def test_method_info_nullable_fields():
    m = MethodInfo(**_method(http_method=None, endpoint=None))
    assert m.http_method is None
    assert m.endpoint is None


def test_method_info_invalid_complexity():
    with pytest.raises(ValidationError):
        MethodInfo(**_method(complexity="extreme"))


def test_method_info_invalid_http_method():
    with pytest.raises(ValidationError):
        MethodInfo(**_method(http_method="OPTIONS"))


def test_method_info_serializes_class_alias():
    m = MethodInfo(**_method())
    data = m.model_dump(by_alias=True)
    assert "class" in data
    assert "class_name" not in data


def _domain(**overrides) -> dict:
    return {
        "name": "catalog",
        "description": "Film catalog domain",
        "file_count": 10,
        "complexity": "medium",
        "methods": [],
        "notable_aspects": ["MapStruct"],
        **overrides,
    }


def test_domain_analysis_valid():
    d = DomainAnalysis(**_domain())
    assert d.name == "catalog"
    assert d.file_count == 10


def test_domain_analysis_round_trip():
    d = DomainAnalysis(**_domain())
    assert DomainAnalysis.model_validate_json(d.model_dump_json()) == d


def test_domain_analysis_invalid_complexity():
    with pytest.raises(ValidationError):
        DomainAnalysis(**_domain(complexity="extreme"))


def test_project_summary_skipped_files_defaults_empty():
    s = ProjectSummary(
        total_files=1,
        total_domains=1,
        total_methods=0,
        overall_complexity="low",
        key_patterns=[],
        notable_aspects=[],
    )
    assert s.skipped_files == []


def test_final_output_structure():
    info = ProjectInfo(
        name="test", overview="o", purpose="p", tech_stack=[], architecture_pattern="MVC"
    )
    summary = ProjectSummary(
        total_files=1,
        total_domains=1,
        total_methods=0,
        overall_complexity="low",
        key_patterns=[],
        notable_aspects=[],
    )
    out = FinalOutput(project=info, domains=[DomainAnalysis(**_domain())], summary=summary)
    assert len(out.domains) == 1
```

- [ ] **Step 3: Run to verify FAIL**

```bash
uv run pytest tests/test_models.py -v
```

Expected: `ModuleNotFoundError: No module named 'src.models'`

- [ ] **Step 4: Create src/models.py**

```python
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class MethodInfo(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    class_name: str = Field(serialization_alias="class")
    method_name: str
    signature: str
    description: str
    http_method: Literal["GET", "POST", "PUT", "DELETE", "PATCH"] | None = None
    endpoint: str | None = None
    complexity: Literal["low", "medium", "high"]


class DomainAnalysis(BaseModel):
    name: str
    description: str
    file_count: int
    complexity: Literal["low", "medium", "high"]
    methods: list[MethodInfo]
    notable_aspects: list[str]


class ProjectInfo(BaseModel):
    name: str
    overview: str
    purpose: str
    tech_stack: list[str]
    architecture_pattern: str


class ProjectSummary(BaseModel):
    total_files: int
    total_domains: int
    total_methods: int
    overall_complexity: Literal["low", "medium", "high"]
    key_patterns: list[str]
    notable_aspects: list[str]
    skipped_files: list[str] = Field(default_factory=list)


class ProjectReport(BaseModel):
    project: ProjectInfo
    summary: ProjectSummary


class FinalOutput(BaseModel):
    project: ProjectInfo
    domains: list[DomainAnalysis]
    summary: ProjectSummary
```

- [ ] **Step 5: Run to verify PASS**

```bash
uv run pytest tests/test_models.py -v
```

Expected: 11 tests PASS.

- [ ] **Step 6: Lint**

```bash
uv run ruff check src/models.py tests/test_models.py
```

Expected: no issues.

- [ ] **Step 7: Commit**

```bash
git add src/models.py tests/__init__.py tests/test_models.py
git commit -m "feat: add Pydantic v2 output schemas"
```

---

### Task 3: FileLoader

**Files:**
- Create: `src/loader.py`
- Create: `tests/test_loader.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_loader.py
from pathlib import Path

from src.loader import FileLoader


def _write(tmp_path: Path, paths: list[str]) -> None:
    for p in paths:
        full = tmp_path / p
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(f"// {p}")


def test_groups_by_services_segment(tmp_path):
    _write(tmp_path, [
        "src/main/java/com/example/services/catalog/ActorController.java",
        "src/main/java/com/example/services/catalog/ActorService.java",
        "src/main/java/com/example/services/rental/RentalController.java",
    ])
    domains = FileLoader(tmp_path).load()
    assert set(domains.keys()) == {"catalog", "rental"}
    assert len(domains["catalog"]) == 2
    assert len(domains["rental"]) == 1


def test_extension_filter_java(tmp_path):
    _write(tmp_path, ["src/Foo.java", "src/Foo.kt", "src/README.md"])
    domains = FileLoader(tmp_path, ext=".java").load()
    total = sum(len(v) for v in domains.values())
    assert total == 1


def test_extension_filter_kotlin(tmp_path):
    _write(tmp_path, ["src/Foo.java", "src/Foo.kt"])
    domains = FileLoader(tmp_path, ext=".kt").load()
    total = sum(len(v) for v in domains.values())
    assert total == 1


def test_empty_source(tmp_path):
    assert FileLoader(tmp_path).load() == {}


def test_fallback_domain_no_marker(tmp_path):
    _write(tmp_path, ["mypackage/Foo.java", "mypackage/Bar.java"])
    domains = FileLoader(tmp_path).load()
    assert "mypackage" in domains
    assert len(domains["mypackage"]) == 2


def test_fallback_domain_top_level_file(tmp_path):
    _write(tmp_path, ["Foo.java"])
    domains = FileLoader(tmp_path).load()
    assert "default" in domains


def test_modules_marker(tmp_path):
    _write(tmp_path, [
        "src/modules/auth/Login.java",
        "src/modules/auth/Logout.java",
        "src/modules/billing/Invoice.java",
    ])
    domains = FileLoader(tmp_path).load()
    assert set(domains.keys()) == {"auth", "billing"}
```

- [ ] **Step 2: Run to verify FAIL**

```bash
uv run pytest tests/test_loader.py -v
```

Expected: `ModuleNotFoundError: No module named 'src.loader'`

- [ ] **Step 3: Create src/loader.py**

```python
from pathlib import Path

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
        return domains

    def _domain_for(self, path: Path) -> str:
        parts = path.relative_to(self.source).parts[:-1]  # exclude filename
        for i, part in enumerate(parts):
            if part in _DOMAIN_MARKERS and i + 1 < len(parts):
                return parts[i + 1]
        for part in parts:
            if part.lower() not in _SKIP_SEGMENTS:
                return part
        return "default"
```

- [ ] **Step 4: Run to verify PASS**

```bash
uv run pytest tests/test_loader.py -v
```

Expected: 7 tests PASS.

- [ ] **Step 5: Lint**

```bash
uv run ruff check src/loader.py tests/test_loader.py
```

Expected: no issues.

- [ ] **Step 6: Commit**

```bash
git add src/loader.py tests/test_loader.py
git commit -m "feat: add FileLoader with domain grouping heuristic"
```

---

### Task 4: DiskCache

**Files:**
- Create: `src/cache.py`
- Create: `tests/test_cache.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_cache.py
from pathlib import Path

from src.cache import DiskCache
from src.models import DomainAnalysis


def _domain(name: str = "catalog") -> DomainAnalysis:
    return DomainAnalysis(
        name=name,
        description="test",
        file_count=1,
        complexity="low",
        methods=[],
        notable_aspects=[],
    )


def test_cache_miss_returns_none(tmp_path):
    cache = DiskCache(tmp_path / ".cache")
    f = tmp_path / "Foo.java"
    f.write_text("class Foo {}")
    assert cache.get([f]) is None


def test_set_then_get_returns_domain(tmp_path):
    cache = DiskCache(tmp_path / ".cache")
    f = tmp_path / "Foo.java"
    f.write_text("class Foo {}")
    domain = _domain()
    cache.set([f], domain)
    assert cache.get([f]) == domain


def test_cache_invalidated_on_content_change(tmp_path):
    cache = DiskCache(tmp_path / ".cache")
    f = tmp_path / "Foo.java"
    f.write_text("class Foo {}")
    cache.set([f], _domain())
    f.write_text("class Foo { void bar() {} }")
    assert cache.get([f]) is None


def test_cache_key_order_independent(tmp_path):
    cache = DiskCache(tmp_path / ".cache")
    f1, f2 = tmp_path / "A.java", tmp_path / "B.java"
    f1.write_text("class A {}")
    f2.write_text("class B {}")
    cache.set([f1, f2], _domain("order-test"))
    assert cache.get([f2, f1]) == _domain("order-test")


def test_cache_creates_directory(tmp_path):
    cache_dir = tmp_path / "nested" / ".cache"
    cache = DiskCache(cache_dir)
    f = tmp_path / "X.java"
    f.write_text("x")
    cache.set([f], _domain())
    assert cache_dir.exists()


def test_multiple_domains_independent(tmp_path):
    cache = DiskCache(tmp_path / ".cache")
    f1, f2 = tmp_path / "A.java", tmp_path / "B.java"
    f1.write_text("class A {}")
    f2.write_text("class B {}")
    cache.set([f1], _domain("alpha"))
    cache.set([f2], _domain("beta"))
    assert cache.get([f1]) == _domain("alpha")
    assert cache.get([f2]) == _domain("beta")
```

- [ ] **Step 2: Run to verify FAIL**

```bash
uv run pytest tests/test_cache.py -v
```

Expected: `ModuleNotFoundError: No module named 'src.cache'`

- [ ] **Step 3: Create src/cache.py**

```python
import hashlib
from pathlib import Path

from src.models import DomainAnalysis


class DiskCache:
    def __init__(self, cache_dir: Path = Path(".cache")) -> None:
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _key(self, files: list[Path]) -> str:
        content = "".join(p.read_text(errors="ignore") for p in sorted(files))
        return hashlib.sha256(content.encode()).hexdigest()

    def get(self, files: list[Path]) -> DomainAnalysis | None:
        path = self.cache_dir / f"{self._key(files)}.json"
        if path.exists():
            return DomainAnalysis.model_validate_json(path.read_text())
        return None

    def set(self, files: list[Path], analysis: DomainAnalysis) -> None:
        path = self.cache_dir / f"{self._key(files)}.json"
        path.write_text(analysis.model_dump_json(indent=2))
```

- [ ] **Step 4: Run to verify PASS**

```bash
uv run pytest tests/test_cache.py -v
```

Expected: 6 tests PASS.

- [ ] **Step 5: Lint**

```bash
uv run ruff check src/cache.py tests/test_cache.py
```

Expected: no issues.

- [ ] **Step 6: Commit**

```bash
git add src/cache.py tests/test_cache.py
git commit -m "feat: add SHA256 disk cache for domain analysis results"
```

---

### Task 5: LLM factory

**Files:**
- Create: `src/llm_factory.py`

No dedicated unit test — this is a thin `init_chat_model` wrapper. The provider validation path is exercised via the CLI (Task 8).

- [ ] **Step 1: Create src/llm_factory.py**

```python
import os

import click
from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

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

    return init_chat_model(f"{provider}:{model}", max_retries=3, temperature=0)
```

- [ ] **Step 2: Lint**

```bash
uv run ruff check src/llm_factory.py
```

Expected: no issues.

- [ ] **Step 3: Commit**

```bash
git add src/llm_factory.py
git commit -m "feat: add provider-agnostic LLM factory (Anthropic/OpenAI/Gemini)"
```

---

### Task 6: Prompts

**Files:**
- Create: `src/prompts.py`

- [ ] **Step 1: Create src/prompts.py**

```python
from langchain_core.prompts import ChatPromptTemplate

EXTRACTION_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        """You are an expert Java code analyst. Analyze the provided Java source files for the \
given domain and extract structured knowledge.

For every public method, extract:
- class_name: the class it belongs to
- method_name: the method name
- signature: the full method signature
- description: one sentence describing what it does
- http_method: GET, POST, PUT, DELETE, or PATCH if it is a REST endpoint, otherwise null
- endpoint: the URL path if it is a REST endpoint (e.g. /api/v1/actors/{id}), otherwise null
- complexity: low (simple CRUD, no branching), medium (some logic, joins, transformations), \
high (complex algorithms, many branches, cross-domain calls)

Also set:
- file_count to the number provided
- complexity for the domain overall
- notable_aspects: list of design patterns or notable aspects you observe""",
    ),
    (
        "human",
        "Domain: {domain_name}\nFile count: {file_count}\n\nSource code:\n{source_code}",
    ),
])

AGGREGATION_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        """You are an expert software architect. Given domain-level analyses of a Java codebase, \
produce a high-level project report.

Infer:
- project name from package names or class names
- overview: 2-3 sentence description of what the project does
- purpose: one sentence on the business purpose
- tech_stack: list of frameworks, libraries, patterns you can identify
- architecture_pattern: e.g. Layered MVC, Hexagonal, CQRS
- overall_complexity across all domains
- key_patterns: list of design patterns observed
- notable_aspects: list of noteworthy aspects

Set total_files, total_domains, and total_methods to 0 — they are filled programmatically.""",
    ),
    (
        "human",
        "Domain analyses:\n\n{domain_summaries}",
    ),
])
```

- [ ] **Step 2: Lint**

```bash
uv run ruff check src/prompts.py
```

Expected: no issues.

- [ ] **Step 3: Commit**

```bash
git add src/prompts.py
git commit -m "feat: add extraction and aggregation prompt templates"
```

---

### Task 7: Pipeline

**Files:**
- Create: `src/pipeline.py`
- Create: `tests/test_pipeline.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_pipeline.py
import asyncio
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
```

- [ ] **Step 2: Run to verify FAIL**

```bash
uv run pytest tests/test_pipeline.py -v
```

Expected: `ModuleNotFoundError: No module named 'src.pipeline'`

- [ ] **Step 3: Create src/pipeline.py**

```python
import asyncio
from pathlib import Path

from langchain_core.language_models import BaseChatModel

from src.cache import DiskCache
from src.loader import FileLoader
from src.models import DomainAnalysis, FinalOutput, ProjectReport, ProjectSummary
from src.prompts import AGGREGATION_PROMPT, EXTRACTION_PROMPT

_MAX_CHARS_PER_DOMAIN = 80_000


def _read_domain(files: list[Path]) -> str:
    parts: list[str] = []
    total = 0
    for f in sorted(files):
        try:
            content = f.read_text(errors="ignore")
        except OSError:
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
    return "\n\n".join(parts)


async def _analyze_domain(
    domain: str,
    files: list[Path],
    llm: BaseChatModel,
    cache: DiskCache | None,
) -> DomainAnalysis:
    if cache:
        cached = cache.get(files)
        if cached:
            return cached

    chain = EXTRACTION_PROMPT | llm.with_structured_output(DomainAnalysis, method="json_schema")
    result: DomainAnalysis = await chain.ainvoke({
        "domain_name": domain,
        "file_count": len(files),
        "source_code": _read_domain(files),
    })

    if cache:
        cache.set(files, result)

    return result


async def _run_aggregation(
    domain_results: list[DomainAnalysis],
    llm: BaseChatModel,
) -> ProjectReport:
    summaries = "\n\n".join(
        f"=== {d.name} ===\n{d.model_dump_json(indent=2)}" for d in domain_results
    )
    chain = AGGREGATION_PROMPT | llm.with_structured_output(ProjectReport, method="json_schema")
    return await chain.ainvoke({"domain_summaries": summaries})


async def run_pipeline(
    source: Path,
    llm: BaseChatModel,
    cache: DiskCache | None,
    ext: str = ".java",
) -> FinalOutput:
    loader = FileLoader(source, ext=ext)
    domains = loader.load()

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
    domain_results: list[DomainAnalysis] = list(await asyncio.gather(*tasks))

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
            skipped_files=report.summary.skipped_files,
        ),
    )
```

- [ ] **Step 4: Run to verify PASS**

```bash
uv run pytest tests/test_pipeline.py -v
```

Expected: 6 tests PASS.

- [ ] **Step 5: Run full suite**

```bash
uv run pytest -v
```

Expected: all tests across all test files PASS.

- [ ] **Step 6: Lint**

```bash
uv run ruff check src/pipeline.py tests/test_pipeline.py
```

Expected: no issues.

- [ ] **Step 7: Commit**

```bash
git add src/pipeline.py tests/test_pipeline.py
git commit -m "feat: add LCEL pipeline with concurrent domain extraction and aggregation"
```

---

### Task 8: CLI

**Files:**
- Create: `src/cli.py`
- Verify: `main.py` (already correct from Task 1)

- [ ] **Step 1: Create src/cli.py**

```python
import asyncio
from pathlib import Path

import click

from src.cache import DiskCache
from src.llm_factory import create_llm
from src.pipeline import run_pipeline


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
    llm = create_llm(provider, model)
    cache = None if no_cache else DiskCache()

    click.echo(f"Analyzing {source} ...")
    result = asyncio.run(run_pipeline(source, llm, cache, ext))

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(result.model_dump_json(indent=2, by_alias=True))
    click.echo(f"Done. Report written to {output}")
```

- [ ] **Step 2: Verify main.py is unchanged**

`main.py` must read exactly:
```python
from src.cli import analyze

if __name__ == "__main__":
    analyze()
```

- [ ] **Step 3: Test --help**

```bash
uv run python main.py --help
```

Expected output includes:
```
Usage: main.py [OPTIONS]

  Analyze a codebase and extract structured knowledge to JSON.

Options:
  --source PATH      Path to codebase root to analyze.  [required]
  --output PATH      Output JSON file path.  [default: output.json]
  --provider TEXT    LLM provider: anthropic | openai | google_genai...
  --model TEXT       Model name (overrides LLM_MODEL env var).
  --no-cache         Disable disk cache.
  --ext TEXT         File extension filter.  [default: .java]
  --help             Show this message and exit.
```

- [ ] **Step 4: Lint**

```bash
uv run ruff check src/cli.py
```

Expected: no issues.

- [ ] **Step 5: Run full suite**

```bash
uv run pytest -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/cli.py
git commit -m "feat: add Click CLI with --source, --output, --provider, --model, --no-cache, --ext"
```

---

### Task 9: Docker & deployment files

**Files:**
- Create: `Dockerfile`
- Create: `docker-compose.yml`
- Create: `.env.example`

- [ ] **Step 1: Create Dockerfile**

```dockerfile
# Stage 1 — install dependencies with uv
FROM python:3.13-slim AS builder
RUN pip install uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Stage 2 — runtime
FROM python:3.13-slim
WORKDIR /app
COPY --from=builder /app/.venv .venv
COPY src/ src/
COPY main.py .
ENV PATH="/app/.venv/bin:$PATH"
ENTRYPOINT ["python", "main.py"]
```

- [ ] **Step 2: Create docker-compose.yml**

```yaml
services:
  analyzer:
    build: .
    env_file: .env
    volumes:
      - ./spring-rest-sakila-main:/codebase:ro
      - ./output:/output
    command:
      - --source
      - /codebase
      - --output
      - /output/report.json
```

- [ ] **Step 3: Create .env.example**

```bash
# Copy to .env and fill in at least one provider's API key.

# Provider: anthropic | openai | google_genai
LLM_PROVIDER=anthropic

# Model (optional — provider default is used if omitted)
# anthropic default:    claude-sonnet-4-6
# openai default:       gpt-4o
# google_genai default: gemini-2.5-flash-lite
LLM_MODEL=

ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GOOGLE_API_KEY=AIza...
```

- [ ] **Step 4: Build Docker image**

```bash
docker build -t codebase-analyzer .
```

Expected: two-stage build completes with no errors.

- [ ] **Step 5: Verify --help inside container**

```bash
docker run --rm codebase-analyzer --help
```

Expected: same help text as `uv run python main.py --help`.

- [ ] **Step 6: Commit**

```bash
git add Dockerfile docker-compose.yml .env.example
git commit -m "feat: add multi-stage Dockerfile and docker-compose for deployment"
```

---

### Task 10: README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Replace README.md**

```markdown
# Codebase Analyzer

Analyzes any Java codebase and extracts structured knowledge — project overview, method
signatures, complexity assessments, and key patterns — to a machine-readable JSON file.

Uses a LangChain LCEL hierarchical pipeline with support for Anthropic Claude, OpenAI, and
Google Gemini as LLM backends.

## Approach

Two-stage hierarchical analysis:

1. **Domain extraction** — source files are grouped by domain directory (e.g. `services/catalog/`
   or `modules/auth/`), then analyzed concurrently. Each domain produces a `DomainAnalysis`
   with all public methods, complexity, and notable aspects.
2. **Aggregation** — domain summaries (not raw code) feed a second LLM call that produces a
   project-level `ProjectReport` with overview, tech stack, and architecture pattern.

A SHA256 disk cache (`.cache/`) skips re-analysis for unchanged domains — re-runs after small
edits cost a fraction of a full run.

## Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) — `pip install uv`
- API key for at least one provider (Anthropic, OpenAI, or Google Gemini)

## Quick Start

```bash
cp .env.example .env        # fill in LLM_PROVIDER and matching API key
uv sync
uv run python main.py --source ./spring-rest-sakila-main --output report.json
```

## CLI Options

| Option | Default | Description |
|---|---|---|
| `--source` | required | Path to codebase root |
| `--output` | `output.json` | Output JSON file |
| `--provider` | `LLM_PROVIDER` env | `anthropic` \| `openai` \| `google_genai` |
| `--model` | `LLM_MODEL` env | Model name |
| `--no-cache` | off | Disable disk cache |
| `--ext` | `.java` | File extension filter |

## Docker

```bash
cp .env.example .env        # fill in your API key
docker compose up           # report written to ./output/report.json
```

## Providers

| Provider | `LLM_PROVIDER` value | Required env var |
|---|---|---|
| Anthropic Claude | `anthropic` | `ANTHROPIC_API_KEY` |
| OpenAI | `openai` | `OPENAI_API_KEY` |
| Google Gemini | `google_genai` | `GOOGLE_API_KEY` |

## Output Schema

See [`docs/superpowers/specs/2026-05-31-codebase-analyzer-design.md`](docs/superpowers/specs/2026-05-31-codebase-analyzer-design.md)
for the full JSON schema.

## Development

```bash
uv sync                     # install all deps including dev
uv run pytest -v            # run tests
uv run ruff check src/      # lint
```

## Assumptions & Limitations

- Domain grouping works best with package-style layouts (`services/`, `modules/`, etc.)
- Domains exceeding 80 000 characters of source are truncated; a `// [truncated]` marker is added
- The aggregation pass is not cached (it only receives summaries, not raw code, so it's fast)
- A full run on the 200-file spring-rest-sakila project costs ~500k–1M tokens depending on provider
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add README with quick start, CLI reference, and architecture overview"
```

---

## Self-Review

**Spec coverage check:**
- ✅ Generic CLI (`--source` path arg) — Task 8
- ✅ Anthropic, OpenAI, Gemini via `init_chat_model` — Task 5
- ✅ Hierarchical pipeline: domain extraction → aggregation — Task 7
- ✅ `asyncio.gather` concurrent per-domain extraction — Task 7 (`run_pipeline`)
- ✅ SHA256 disk cache + `--no-cache` — Tasks 4, 8
- ✅ Pydantic v2 schemas enforced via `with_structured_output(method="json_schema")` — Tasks 2, 7
- ✅ JSON output with `by_alias=True` so "class_name" serializes as "class" — Task 8 (`cli.py`)
- ✅ 80k character per-domain truncation — Task 7 (`_read_domain`)
- ✅ Unreadable files skipped — Task 7 (`_read_domain` OSError catch)
- ✅ Provider not configured → clear error — Task 5
- ✅ Numeric summary fields (total_files/domains/methods) computed from actual results — Task 7
- ✅ test_models, test_loader, test_cache, test_pipeline — Tasks 2–4, 7
- ✅ All pipeline tests use mocks, zero API cost — Task 7
- ✅ Multi-stage Dockerfile + docker-compose — Task 9
- ✅ `.env.example` — Task 9
- ✅ README — Task 10
- ✅ uv for deps, ruff for linting — Task 1

**Placeholder scan:** No TBDs, TODOs, or vague steps. All code steps contain complete, runnable code.

**Type consistency:**
- `DomainAnalysis` defined Task 2 → used in Tasks 4 (`cache.py`), 7 (`pipeline.py`) ✅
- `_analyze_domain(domain, files, llm, cache)` defined Task 7 → patched as `src.pipeline._analyze_domain` in tests ✅
- `_run_aggregation(domain_results, llm)` defined Task 7 → patched as `src.pipeline._run_aggregation` in tests ✅
- `_read_domain(files)` defined Task 7 → imported in tests as `from src.pipeline import _read_domain` ✅
- `DiskCache()` default `.cache/` in `cli.py` → matches `DiskCache.__init__` default in `cache.py` ✅
- `model_dump_json(indent=2, by_alias=True)` in `cli.py` → `serialization_alias="class"` on `MethodInfo.class_name` ✅
