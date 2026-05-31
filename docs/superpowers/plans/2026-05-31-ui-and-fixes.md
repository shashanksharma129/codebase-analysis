# UI & Code Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the skipped_files tracking bug in the pipeline, add new deps, build a Streamlit UI that accepts a GitHub repo URL and shows structured analysis results, and update the README.

**Architecture:** Four independent tasks executed in order: (1) pipeline bug fix, (2) dependency update, (3) single-file Streamlit app `ui.py` that reuses `src/pipeline.py` and `src/llm_factory.py`, (4) README update.

**Tech Stack:** Python 3.13, uv, streamlit, python-dotenv, requests, existing LangChain pipeline.

---

## File Map

```
src/pipeline.py        fix _read_domain → returns (str, list[str]); thread skipped through run_pipeline
tests/test_pipeline.py update 3 existing tests (unpack tuple); add 1 new test
pyproject.toml         add streamlit, python-dotenv, requests, tenacity to dependencies
ui.py                  new Streamlit app (single file)
tests/test_ui.py       new — tests parse_github_url only
README.md              add "Web UI" section
```

---

### Task 1: Fix skipped_files tracking in pipeline

**Files:**
- Modify: `src/pipeline.py`
- Modify: `tests/test_pipeline.py`

- [ ] **Step 1: Update tests to expect the new tuple return and add skipped_files test**

Replace the entire `tests/test_pipeline.py` with:

```python
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

    with (
        patch("src.pipeline._analyze_domain", new=AsyncMock(return_value=(_make_domain("catalog"), []))),
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
        patch("src.pipeline._analyze_domain", new=AsyncMock(return_value=(_make_domain("catalog"), []))),
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
```

- [ ] **Step 2: Run tests to verify FAIL**

```bash
cd /home/shashank_sharma1/code/codebase-analysis && uv run pytest tests/test_pipeline.py -v 2>&1 | tail -20
```

Expected: failures because `_read_domain` still returns `str`, not a tuple.

- [ ] **Step 3: Update src/pipeline.py**

Replace the entire file with:

```python
import asyncio
from pathlib import Path

from langchain_core.language_models import BaseChatModel

from src.cache import DiskCache
from src.loader import FileLoader
from src.models import DomainAnalysis, FinalOutput, ProjectReport, ProjectSummary
from src.prompts import AGGREGATION_PROMPT, EXTRACTION_PROMPT

_MAX_CHARS_PER_DOMAIN = 80_000


def _read_domain(files: list[Path]) -> tuple[str, list[str]]:
    parts: list[str] = []
    skipped: list[str] = []
    total = 0
    for f in sorted(files):
        try:
            content = f.read_text(errors="ignore")
        except OSError:
            skipped.append(str(f))
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
    if cache:
        cached = cache.get(files)
        if cached:
            return cached, []

    source, skipped = _read_domain(files)
    chain = EXTRACTION_PROMPT | llm.with_structured_output(DomainAnalysis, method="json_schema")
    result: DomainAnalysis = await chain.ainvoke({
        "domain_name": domain,
        "file_count": len(files),
        "source_code": source,
    })

    if cache:
        cache.set(files, result)

    return result, skipped


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
```

- [ ] **Step 4: Run tests to verify PASS**

```bash
cd /home/shashank_sharma1/code/codebase-analysis && uv run pytest tests/test_pipeline.py -v
```

Expected: 7 tests PASS.

- [ ] **Step 5: Run full suite**

```bash
cd /home/shashank_sharma1/code/codebase-analysis && uv run pytest -v
```

Expected: 31 tests PASS (was 30 — new skipped_files test added).

- [ ] **Step 6: Lint**

```bash
cd /home/shashank_sharma1/code/codebase-analysis && uv run ruff check src/pipeline.py tests/test_pipeline.py
```

Expected: no issues.

- [ ] **Step 7: Commit**

```bash
cd /home/shashank_sharma1/code/codebase-analysis && git add src/pipeline.py tests/test_pipeline.py && git commit -m "fix: track unreadable files in skipped_files summary field"
```

---

### Task 2: Add dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Update pyproject.toml dependencies**

Replace the `[project]` dependencies list with:

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
    "tenacity",
    "streamlit",
    "python-dotenv",
    "requests",
]
```

The rest of `pyproject.toml` (dev deps, ruff config, pytest config) stays unchanged.

- [ ] **Step 2: Sync dependencies**

```bash
cd /home/shashank_sharma1/code/codebase-analysis && uv sync
```

Expected: resolves and installs new packages, updates `uv.lock`.

- [ ] **Step 3: Run full suite to confirm nothing broke**

```bash
cd /home/shashank_sharma1/code/codebase-analysis && uv run pytest -v
```

Expected: 31 tests PASS.

- [ ] **Step 4: Commit**

```bash
cd /home/shashank_sharma1/code/codebase-analysis && git add pyproject.toml uv.lock && git commit -m "chore: add streamlit, python-dotenv, requests, tenacity dependencies"
```

---

### Task 3: Implement ui.py

**Files:**
- Create: `ui.py`
- Create: `tests/test_ui.py`

- [ ] **Step 1: Write failing tests for parse_github_url**

```python
# tests/test_ui.py
import pytest

from ui import parse_github_url


def test_parse_simple_url():
    owner, repo, branch = parse_github_url("https://github.com/owner/repo")
    assert owner == "owner"
    assert repo == "repo"
    assert branch == "main"


def test_parse_url_with_branch():
    owner, repo, branch = parse_github_url("https://github.com/owner/repo/tree/develop")
    assert owner == "owner"
    assert repo == "repo"
    assert branch == "develop"


def test_parse_url_with_git_suffix():
    owner, repo, branch = parse_github_url("https://github.com/owner/repo.git")
    assert owner == "owner"
    assert repo == "repo"
    assert branch == "main"


def test_parse_url_with_trailing_slash():
    owner, repo, branch = parse_github_url("https://github.com/owner/repo/")
    assert owner == "owner"
    assert repo == "repo"
    assert branch == "main"


def test_parse_invalid_url_wrong_host():
    with pytest.raises(ValueError):
        parse_github_url("https://gitlab.com/owner/repo")


def test_parse_invalid_url_not_a_url():
    with pytest.raises(ValueError):
        parse_github_url("not-a-url")
```

- [ ] **Step 2: Run tests to verify FAIL**

```bash
cd /home/shashank_sharma1/code/codebase-analysis && uv run pytest tests/test_ui.py -v 2>&1 | head -10
```

Expected: `ModuleNotFoundError: No module named 'ui'`

- [ ] **Step 3: Create ui.py**

```python
import asyncio
import io
import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

import click
import requests
import streamlit as st
from dotenv import load_dotenv

from src.cache import DiskCache
from src.llm_factory import create_llm
from src.pipeline import run_pipeline

load_dotenv()

st.set_page_config(page_title="Codebase Analyzer", layout="wide")

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


def _download_and_extract(owner: str, repo: str, branch: str, dest: Path) -> Path:
    zip_url = f"https://github.com/{owner}/{repo}/archive/refs/heads/{branch}.zip"
    resp = requests.get(zip_url, timeout=60)
    if resp.status_code != 200:
        raise RuntimeError(f"Failed to download repository: HTTP {resp.status_code}")
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        zf.extractall(dest)
    return next(dest.iterdir())


# LLM + cache initialised once at startup
try:
    _llm = create_llm()
    _cache = DiskCache()
except click.ClickException as e:
    st.error(e.format_message())
    st.stop()

# ── Page header ──────────────────────────────────────────────────────────────
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

    try:
        with st.status("Downloading repository...", expanded=True) as status:
            source = _download_and_extract(owner, repo, branch, Path(tmp))
            status.update(label="Analyzing repository...")
            result = asyncio.run(run_pipeline(source, _llm, _cache))
            status.update(label="Done.", state="complete")
    except RuntimeError as e:
        error_msg = str(e)
    except requests.RequestException as e:
        error_msg = f"Network error: {e}"
    except Exception as e:
        error_msg = f"Analysis failed: {e}"
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

- [ ] **Step 4: Run tests to verify PASS**

```bash
cd /home/shashank_sharma1/code/codebase-analysis && uv run pytest tests/test_ui.py -v
```

Expected: 6 tests PASS.

- [ ] **Step 5: Run full suite**

```bash
cd /home/shashank_sharma1/code/codebase-analysis && uv run pytest -v
```

Expected: 37 tests PASS (31 existing + 6 new).

- [ ] **Step 6: Lint**

```bash
cd /home/shashank_sharma1/code/codebase-analysis && uv run ruff check ui.py tests/test_ui.py
```

Expected: no issues.

- [ ] **Step 7: Commit**

```bash
cd /home/shashank_sharma1/code/codebase-analysis && git add ui.py tests/test_ui.py && git commit -m "feat: add Streamlit UI with GitHub URL input and dual-tab results"
```

---

### Task 4: Update README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add Web UI section to README.md**

Insert the following block into `README.md` directly after the `## Quick Start` section (after the closing ` ``` ` of the quick start code block) and before the `## CLI Options` section:

```markdown
## Web UI

A browser-based interface that accepts a public GitHub repository URL and displays results in two tabs — a human-readable summary and a raw JSON viewer with download.

```bash
cp .env.example .env        # fill in LLM_PROVIDER and matching API key
uv sync
streamlit run ui.py
```

Open `http://localhost:8501` in your browser, paste a GitHub URL (e.g. `https://github.com/codejsha/spring-rest-sakila`), and click **Analyze**.

> **Note:** Only public repositories are supported (no authentication).
```

- [ ] **Step 2: Verify README renders correctly**

```bash
cd /home/shashank_sharma1/code/codebase-analysis && grep -n "Web UI" README.md
```

Expected: prints the line number where `## Web UI` appears.

- [ ] **Step 3: Commit**

```bash
cd /home/shashank_sharma1/code/codebase-analysis && git add README.md && git commit -m "docs: add Web UI section to README"
```

---

## Self-Review

**Spec coverage:**
- ✅ Streamlit framework — Task 3 (`ui.py`)
- ✅ ZIP download (no git) — Task 3 (`_download_and_extract`)
- ✅ `.env` / `load_dotenv()` for LLM config — Task 3 (top of `ui.py`)
- ✅ `create_llm()` wrapped in `try/except click.ClickException` — Task 3
- ✅ URL parser handles 3 formats + raises `ValueError` on invalid — Task 3
- ✅ Progress via `st.status` — Task 3
- ✅ Summary tab: project name, overview, purpose, metrics row, tech stack, domain cards — Task 3
- ✅ Raw JSON tab: `st.json` + download button — Task 3
- ✅ Empty repo shows info message — Task 3
- ✅ Error messages shown via `st.error` — Task 3
- ✅ Temp dir cleaned in `finally` — Task 3
- ✅ `skipped_files` correctly populated — Task 1
- ✅ `tenacity` in `pyproject.toml` — Task 2
- ✅ README Web UI section — Task 4
- ✅ 6 URL parsing tests + 7 pipeline tests = 37 total — Tasks 1 and 3

**Placeholder scan:** No TBDs, TODOs, or vague steps. All code is complete and runnable.

**Type consistency:**
- `parse_github_url` returns `tuple[str, str, str]` → used in Task 3 as `owner, repo, branch_from_url = parse_github_url(url)` ✅
- `_read_domain` returns `tuple[str, list[str]]` → used as `source, skipped = _read_domain(files)` in `_analyze_domain` ✅
- `_analyze_domain` returns `tuple[DomainAnalysis, list[str]]` → mocked as `AsyncMock(return_value=(_make_domain(...), []))` in tests ✅
- `run_pipeline` return type `FinalOutput` unchanged → `result.model_dump_json(indent=2, by_alias=True)` in `ui.py` ✅
