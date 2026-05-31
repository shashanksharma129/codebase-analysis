# Multi-Language Analyzer — Design Spec

**Date:** 2026-06-01
**Status:** Approved

---

## Overview

Extend the Codebase Analyzer to support Python repositories alongside Java, using a strategy
pattern so future languages (Go, TypeScript, Rust) can be added without touching the pipeline
core. The Python analyzer is production-grade: it uses Python's `ast` module for structural
pre-extraction before the LLM call, and a LangGraph graph for per-domain analysis with
validation and retry.

**Invocation (unchanged interface):**
```bash
streamlit run ui.py                                    # UI — language selector dropdown
uv run python main.py --language python --source ...   # CLI
uv run python main.py --language java  --source ...    # CLI (unchanged behavior)
```

---

## Goals

1. Python repos analyze correctly — domains, methods, complexity, routes for web service repos.
2. Java behavior is byte-for-byte identical to today — zero regression.
3. The pipeline core (`run_pipeline`) has no language-specific logic.
4. Adding a third language (Go, TypeScript) requires creating one new file in `src/analyzers/`,
   no changes to `pipeline.py`, `ui.py`, or `cli.py`.

---

## Non-Goals

- Auto-detection of language from repo contents (user selects language explicitly).
- Go, Rust, TypeScript analyzers (designed for, not built now).
- Plugin/dynamic loading system (two languages don't warrant it).
- LangGraph for the Java analyzer (simple LCEL chain is correct there).

---

## File Map

```
src/analyzers/
    __init__.py          exports: get_analyzer, LanguageAnalyzer
    base.py              LanguageAnalyzer ABC
    factory.py           get_analyzer(ext: str) -> LanguageAnalyzer
    java.py              JavaAnalyzer — wraps current pipeline behavior
    python.py            PythonAnalyzer — AST + LangGraph
src/ast_utils.py         Python AST extraction (ASTSummary, FileSummary, MethodSummary)
src/models.py            add language: str field to FinalOutput
src/pipeline.py          accept LanguageAnalyzer; remove ext param; remove _analyze_domain
src/cli.py               --language option (replaces --ext); call get_analyzer
ui.py                    language selectbox; pass analyzer to run_pipeline
pyproject.toml           add langgraph dependency
tests/test_ast_utils.py          NEW — AST extraction and framework detection
tests/test_python_analyzer.py    NEW — LangGraph graph, node-level, retry behavior
tests/test_java_analyzer.py      NEW — JavaAnalyzer delegates correctly
tests/test_factory.py            NEW — get_analyzer returns correct type
tests/test_pipeline.py           UPDATE — pass analyzer instead of ext
tests/test_cli.py                NEW — --language flag (no existing test_cli.py)
```

No changes to: `src/prompts.py`, `src/cache.py`, `src/loader.py`, `src/llm_factory.py`.

---

## Architecture

```
Entry Points (ui.py, cli.py)
        │
        ▼
  get_analyzer(ext)          factory.py
  ".java" → JavaAnalyzer
  ".py"   → PythonAnalyzer
        │
        ▼
  run_pipeline(source, llm, cache, analyzer)    pipeline.py
    analyzer.get_domain_map(source)
    asyncio.gather(analyzer.analyze_domain(...) for each domain)
    _run_aggregation(domains, llm, analyzer.get_aggregation_prompt())
        │
        ├── JavaAnalyzer.analyze_domain()
        │     LCEL: EXTRACTION_PROMPT | llm.with_structured_output(DomainAnalysis)
        │     FileLoader for domain discovery
        │
        └── PythonAnalyzer.analyze_domain()
              LangGraph: ast_extract → llm_analyze → validate ──► END
                                             ▲               │
                                             └── retry ──────┘ (max 2)
```

---

## LanguageAnalyzer ABC (`src/analyzers/base.py`)

```python
from abc import ABC, abstractmethod
from pathlib import Path
from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from src.cache import DiskCache
from src.models import DomainAnalysis


class LanguageAnalyzer(ABC):

    @property
    @abstractmethod
    def ext(self) -> str:
        """File extension, e.g. '.java', '.py'"""

    @abstractmethod
    def get_domain_map(self, source: Path) -> dict[str, list[Path]]:
        """Discover domains and their source files."""

    @abstractmethod
    async def analyze_domain(
        self,
        domain: str,
        files: list[Path],
        llm: BaseChatModel,
        cache: DiskCache | None,
    ) -> tuple[DomainAnalysis, list[str]]:
        """Analyze one domain. Returns (analysis, skipped_file_paths)."""

    @abstractmethod
    def get_aggregation_prompt(self) -> ChatPromptTemplate:
        """Prompt template for cross-domain aggregation step."""
```

The ABC surface is exactly what `run_pipeline` calls — nothing more.

---

## Factory (`src/analyzers/factory.py`)

```python
from src.analyzers.base import LanguageAnalyzer
from src.analyzers.java import JavaAnalyzer
from src.analyzers.python import PythonAnalyzer

_REGISTRY: dict[str, type[LanguageAnalyzer]] = {
    ".java": JavaAnalyzer,
    ".py":   PythonAnalyzer,
}

def get_analyzer(ext: str) -> LanguageAnalyzer:
    cls = _REGISTRY.get(ext)
    if cls is None:
        supported = ", ".join(_REGISTRY)
        raise ValueError(f"Unsupported extension '{ext}'. Supported: {supported}")
    return cls()
```

---

## JavaAnalyzer (`src/analyzers/java.py`)

A faithful extraction of the current `_analyze_domain` and `FileLoader` usage. Zero new logic.

```python
class JavaAnalyzer(LanguageAnalyzer):
    ext = ".java"

    def get_domain_map(self, source: Path) -> dict[str, list[Path]]:
        from src.loader import FileLoader
        return FileLoader(source, self.ext).load()

    async def analyze_domain(self, domain, files, llm, cache):
        # Move the body of _analyze_domain() from src/pipeline.py verbatim.
        # That function: checks cache, calls _read_domain(), runs EXTRACTION_PROMPT
        # chain with llm.with_structured_output(DomainAnalysis), sets cache, wraps
        # everything in tracer.start_as_current_span("analyze_domain", attributes=...)
        # with span.record_exception + StatusCode.ERROR on exception.
        ...

    def get_aggregation_prompt(self):
        from src.prompts import AGGREGATION_PROMPT
        return AGGREGATION_PROMPT
```

All existing Java tests pass unmodified (behavior is identical).

---

## AST Utilities (`src/ast_utils.py`)

### Data Structures

```python
@dataclass
class MethodSummary:
    name: str
    signature: str       # "async def get_user(user_id: int) -> UserResponse"
    decorators: list[str]  # ["@router.get('/users/{user_id}')"]
    is_async: bool
    class_name: str | None
    docstring: str | None

@dataclass
class FileSummary:
    path: str
    imports: list[str]
    classes: list[str]   # "UserRouter(APIRouter)"
    methods: list[MethodSummary]
    docstring: str | None

@dataclass
class ASTSummary:
    files: list[FileSummary]
    detected_framework: str | None  # "fastapi"|"flask"|"django"|"starlette"|None
    has_async: bool
    project_type: str               # "web_service"|"library"|"cli"|"data_science"|"mixed"
```

### Framework Detection Rules

| Import / Pattern | Framework | project_type |
|---|---|---|
| `from fastapi import` or `FastAPI()` | `fastapi` | `web_service` |
| `from flask import Flask` | `flask` | `web_service` |
| `from django` or `urlpatterns =` | `django` | `web_service` |
| `from starlette` | `starlette` | `web_service` |
| `import click` + `@click.command` | — | `cli` |
| `import pandas` / `numpy` / `sklearn` / `torch` | — | `data_science` |
| none of the above | — | `library` |

### Key Functions

```python
def extract_ast_summary(files: list[Path]) -> tuple[ASTSummary, list[str]]:
    """Parse all files. Returns (summary, skipped_paths) where skipped = parse errors."""

def render_ast_summary(summary: ASTSummary) -> str:
    """Serialize ASTSummary to compact text block for LLM prompt."""
```

**`render_ast_summary` output format** (what the LLM receives instead of raw source):
```
=== src/api/users.py ===
Classes:
  UserRouter(APIRouter):
    async def get_user(user_id: int) -> UserResponse
      @router.get("/users/{user_id}")
    async def create_user(body: UserCreate) -> UserResponse
      @router.post("/users")
  UserService:
    async def get_by_id(id: int) -> User | None
    async def create(data: UserCreate) -> User

Module functions:
  def startup() -> None
    @app.on_event("startup")
```

Requires Python 3.9+ (`ast.unparse`). Project already requires 3.12+.

---

## PythonAnalyzer (`src/analyzers/python.py`)

### Domain Discovery

If any immediate subdirectory of `source` contains an `__init__.py`, use package-based
discovery: each subdirectory with `__init__.py` is one domain, its `.py` files (recursively)
are its members. If no `__init__.py` exists at the top level, fall back to the existing
`FileLoader` heuristic (marker-based domain naming).

Python-specific `_SKIP_SEGMENTS` additions:
`__pycache__`, `.venv`, `venv`, `env`, `site-packages`, `dist`, `build`, `migrations`,
`.eggs`, `node_modules`.

### LangGraph State

```python
class DomainAnalysisState(TypedDict):
    domain: str
    files: list[Path]
    llm: BaseChatModel
    ast_summary: ASTSummary | None
    analysis: DomainAnalysis | None
    validation_errors: list[str]
    retry_count: int
    skipped_files: list[str]
```

### Graph Nodes

**`ast_extract(state)`**
- Runs `extract_ast_summary(state["files"])`
- Stores result in `state["ast_summary"]`
- Appends parse-failed paths to `state["skipped_files"]`
- Pure Python, no LLM call, always succeeds

**`llm_analyze(state)`**
- Selects prompt variant based on `ast_summary.project_type`:
  - `"web_service"` → prompt focused on routes, HTTP methods, request/response shapes
  - other → prompt focused on public API surface, module purpose, data flows
- On retry (`retry_count > 0`): appends validation feedback to system message:
  `"Previous attempt was missing: {validation_errors}. Ensure all detected methods appear."`
- Calls `llm.with_structured_output(DomainAnalysis, method="json_schema")`
- Increments `retry_count`

**`validate(state)`**
- Three deterministic checks (no LLM):
  1. Every method name in `ASTSummary` appears in at least one `MethodInfo.method_name`
  2. Every `MethodInfo.signature` is non-empty
  3. `DomainAnalysis.complexity` is one of `"low"` / `"medium"` / `"high"`
- Sets `validation_errors` list

### Graph Edges

```
START → ast_extract → llm_analyze → validate
                          ▲              │
                          │   invalid    │  retry_count < 2
                          └─────────────┘
                                         │  valid OR retry_count >= 2
                                         ▼
                                        END
```

Retry semantics: `retry_count` starts at 0 and is incremented inside `llm_analyze` before
returning. After the first LLM call, `retry_count=1`. After the second, `retry_count=2`.
`validate` routes back to `llm_analyze` only when `retry_count < 2`, so a maximum of 3
total LLM calls per domain (initial + 2 retries). On `retry_count >= 2` with remaining
errors: log `logger.warning`, return best-effort `state["analysis"]`.

### Python Prompts

Two `ChatPromptTemplate` constants defined in `python.py`:

**`PYTHON_EXTRACTION_PROMPT`** (web_service variant, defined in `python.py`):
```python
PYTHON_WEB_EXTRACTION_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are an expert Python code analyst specializing in web services.
Analyze the pre-extracted AST structure of a Python domain and extract structured knowledge.

For every method (identified by its signature and decorators):
- class_name: the class it belongs to, or null for module-level functions
- method_name: the function name
- signature: the full signature including type hints, e.g. "async def get_user(user_id: int) -> UserResponse"
- description: one sentence describing what it does
- http_method: GET/POST/PUT/DELETE/PATCH if it is a route handler (check @router.X / @app.X decorators), otherwise null
- endpoint: the URL path from the decorator, e.g. "/users/{user_id}", otherwise null
- complexity: low (simple CRUD, no branching), medium (some logic), high (complex, cross-domain)

Also set domain complexity and notable_aspects (design patterns, async usage, dependency injection)."""),
    ("human", "Domain: {domain_name}\nFile count: {file_count}\n\nPre-extracted structure:\n{ast_text}"),
])

PYTHON_LIBRARY_EXTRACTION_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are an expert Python code analyst.
Analyze the pre-extracted AST structure of a Python domain and extract structured knowledge.

For every public method and function:
- class_name, method_name, signature (with full type hints), description, complexity
- http_method and endpoint: null (not a web service)
- Focus on: public API surface, data transformations, algorithms, async patterns

Also set domain complexity and notable_aspects."""),
    ("human", "Domain: {domain_name}\nFile count: {file_count}\n\nPre-extracted structure:\n{ast_text}"),
])
```

**`PYTHON_AGGREGATION_PROMPT`** (defined in `python.py`):
```python
PYTHON_AGGREGATION_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are an expert software architect. Given domain-level analyses of a Python codebase,
produce a high-level project report.

Infer:
- project name from module/package names
- overview: 2-3 sentence description
- purpose: one sentence business purpose
- tech_stack: frameworks, libraries (FastAPI, SQLAlchemy, Pydantic, Celery, etc.)
- architecture_pattern: e.g. Clean Architecture, Layered, Microservice, MVC (Django), Event-driven
- overall_complexity, key_patterns, notable_aspects

Set total_files, total_domains, total_methods to 0 — filled programmatically."""),
    ("human", "Domain analyses:\n\n{domain_summaries}"),
])
```

### `analyze_domain` Public Interface

```python
async def analyze_domain(self, domain, files, llm, cache):
    if cache:
        cached = cache.get(files)
        if cached:
            return cached, []

    graph = self._get_graph()   # compiled once, cached on instance
    final_state = await graph.ainvoke({
        "domain": domain,
        "files": files,
        "llm": llm,
        "ast_summary": None,
        "analysis": None,
        "validation_errors": [],
        "retry_count": 0,
        "skipped_files": [],
    })

    analysis = final_state["analysis"]
    if cache and analysis:
        cache.set(files, analysis)

    return analysis, final_state["skipped_files"]
```

---

## Pipeline Changes (`src/pipeline.py`)

### Signature

```python
# Before
async def run_pipeline(source, llm, cache, ext=".java") -> FinalOutput

# After
async def run_pipeline(source, llm, cache, analyzer: LanguageAnalyzer) -> FinalOutput
```

### Body Changes

- `FileLoader(source, ext).load()` → `analyzer.get_domain_map(source)`
- `_analyze_domain(domain, files, llm, cache)` → `analyzer.analyze_domain(domain, files, llm, cache)`
- `AGGREGATION_PROMPT` → `analyzer.get_aggregation_prompt()`
- `_analyze_domain` module-level function removed (lives in `JavaAnalyzer` / `PythonAnalyzer`)
- `span.set_attribute("ext", ext)` → `span.set_attribute("language", analyzer.ext.lstrip("."))`
- All other logic (asyncio.gather, error handling, FinalOutput assembly) unchanged

### `_run_aggregation` Signature

```python
async def _run_aggregation(
    domain_results: list[DomainAnalysis],
    llm: BaseChatModel,
    aggregation_prompt: ChatPromptTemplate,   # new param
) -> ProjectReport:
```

---

## Model Changes (`src/models.py`)

One field added to `FinalOutput`, backward-compatible:

```python
class FinalOutput(BaseModel):
    language: str = "java"    # new — set by run_pipeline from analyzer.ext
    project: ProjectInfo
    domains: list[DomainAnalysis]
    summary: ProjectSummary
```

`run_pipeline` sets `language=analyzer.ext.lstrip(".")` when assembling output.

---

## CLI Changes (`src/cli.py`)

```python
@click.option(
    "--language",
    default="java",
    type=click.Choice(["java", "python"]),
    help="Language of the codebase to analyze.",
)
def analyze(..., language: str, ...):
    setup_telemetry()
    analyzer = get_analyzer("." + language)
    ...
    result = asyncio.run(run_pipeline(source, llm, cache, analyzer))
```

The `--ext` option is removed. The `analyze_repo` OTel span attribute updates from `ext` to `language`.

---

## UI Changes (`ui.py`)

```python
lang = st.selectbox("Language", ["Java", "Python"], index=0)
analyzer = get_analyzer("." + lang.lower())

# In the analysis block:
result = asyncio.run(run_pipeline(source, _llm, _cache, analyzer))

# Empty state:
st.info(f"No {lang.lower()} files detected in this repository.")
```

Language selectbox placed between the URL input and the Analyze button.

---

## Dependencies (`pyproject.toml`)

Add to `[project].dependencies`:
```toml
"langgraph>=0.2",
```

LangGraph is in the LangChain ecosystem; no additional auth/config required.

---

## Testing Strategy

### New Test Files

**`tests/test_ast_utils.py`**
- `test_extract_simple_class` — class with typed methods extracted correctly
- `test_extract_async_method` — `is_async=True` for `async def`
- `test_extract_fastapi_decorator` — `@router.get("/path")` captured in decorators
- `test_detect_framework_fastapi` — import triggers `detected_framework="fastapi"`
- `test_detect_framework_flask` — import triggers `detected_framework="flask"`
- `test_detect_project_type_cli` — click import → `project_type="cli"`
- `test_render_ast_summary` — output contains class names, signatures, decorators
- `test_extract_syntax_error_file` — parse-failed file appears in skipped list, others extracted

**`tests/test_python_analyzer.py`**
- `test_ast_extract_node` — call node directly, verify ASTSummary populated
- `test_llm_analyze_node_web_service` — web_service project_type uses route-focused prompt
- `test_llm_analyze_node_library` — non-web project_type uses library prompt
- `test_validate_node_passes` — all methods present → no validation_errors
- `test_validate_node_fails_missing_method` — missing method → validation_errors populated
- `test_graph_retry_on_validation_failure` — bad first LLM response → retry → success
- `test_graph_max_retries_exhausted` — 2 failures → best-effort result returned, no exception
- `test_analyze_domain_cache_hit` — cache hit bypasses graph entirely
- `test_analyze_domain_uses_package_discovery` — `__init__.py` dirs used as domain boundaries

**`tests/test_java_analyzer.py`**
- `test_get_domain_map_delegates_to_file_loader` — returns same result as `FileLoader`
- `test_analyze_domain_uses_extraction_prompt` — EXTRACTION_PROMPT used (not Python prompt)
- `test_get_aggregation_prompt_returns_java_prompt` — returns `AGGREGATION_PROMPT`

**`tests/test_factory.py`**
- `test_get_analyzer_java` — `.java` → `JavaAnalyzer`
- `test_get_analyzer_python` — `.py` → `PythonAnalyzer`
- `test_get_analyzer_unsupported` — unknown ext → `ValueError`

**`tests/test_pipeline.py` (updates)**
- Replace `ext=".java"` in all existing tests with `analyzer=JavaAnalyzer()`
- Add `test_run_pipeline_python` — passes `PythonAnalyzer()`, verifies `FinalOutput.language == "python"`

---

## Error Handling

| Scenario | Behavior |
|---|---|
| AST parse error on one file | File skipped, added to `skipped_files`, rest of domain analyzed |
| LLM returns invalid structured output | Pydantic validation raises; caught in `llm_analyze` node, logged, retried |
| Validation fails after 2 retries | Best-effort result returned with `logger.warning`; no exception raised |
| Unknown `--language` / ext | `get_analyzer` raises `ValueError`; CLI surfaces as Click error |
| Python repo with no `.py` files | `get_domain_map` returns `{}`; pipeline produces empty `FinalOutput` with correct message |

---

## Constraints

- `ast.unparse()` requires Python 3.9+; project already requires 3.12+.
- LangGraph graph is compiled once per `PythonAnalyzer` instance and reused across `analyze_domain` calls (thread-safe; `ainvoke` is stateless per call).
- Java behavior is identical to today — `JavaAnalyzer` is a mechanical extraction, not a rewrite.
- The `--ext` CLI flag is removed; `--language` replaces it. This is a breaking change to the CLI interface, acceptable since `--ext` was the internal mechanism, `--language` is the user-facing concept.
