import logging
import time
from pathlib import Path
from typing import TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import END, StateGraph
from opentelemetry import trace
from opentelemetry.trace import StatusCode

from src.analyzers.base import LanguageAnalyzer
from src.ast_utils import ASTSummary, extract_ast_summary, render_ast_summary
from src.cache import DiskCache
from src.loader import FileLoader
from src.models import DomainAnalysis

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

_SKIP_SEGMENTS = frozenset({
    "__pycache__", ".venv", "venv", "env", "site-packages",
    "dist", "build", "migrations", ".eggs", "node_modules",
    ".git", ".tox", ".mypy_cache", ".pytest_cache",
})

PYTHON_WEB_EXTRACTION_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are an expert Python code analyst specializing in web services.
Analyze the pre-extracted AST structure of a Python domain and extract structured knowledge.

For every method (identified by its signature and decorators):
- class_name: the class it belongs to, or null for module-level functions
- method_name: the function name
- signature: the full signature including type hints, e.g. "async def get_user(user_id: int) -> UserResponse"
- description: one sentence describing what it does
- http_method: GET/POST/PUT/DELETE/PATCH if it is a route handler (check @router.X / @app.X decorators), otherwise null
- endpoint: the URL path from the decorator, e.g. "/users/{{user_id}}", otherwise null
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


class DomainAnalysisState(TypedDict):
    domain: str
    files: list[Path]
    llm: BaseChatModel
    ast_summary: ASTSummary | None
    analysis: DomainAnalysis | None
    validation_errors: list[str]
    retry_count: int
    skipped_files: list[str]


def _ast_extract(state: DomainAnalysisState) -> DomainAnalysisState:
    summary, skipped = extract_ast_summary(state["files"])
    return {**state, "ast_summary": summary, "skipped_files": skipped}


async def _llm_analyze(state: DomainAnalysisState) -> DomainAnalysisState:
    ast_summary = state["ast_summary"]
    assert ast_summary is not None

    prompt = (
        PYTHON_WEB_EXTRACTION_PROMPT
        if ast_summary.project_type == "web_service"
        else PYTHON_LIBRARY_EXTRACTION_PROMPT
    )

    system_suffix = ""
    if state["retry_count"] > 0 and state["validation_errors"]:
        errors = "; ".join(state["validation_errors"])
        system_suffix = f"\n\nPrevious attempt was missing: {errors}. Ensure all detected methods appear."

    chain = prompt | state["llm"].with_structured_output(DomainAnalysis, method="json_schema")

    invoke_input = {
        "domain_name": state["domain"],
        "file_count": len(state["files"]),
        "ast_text": render_ast_summary(ast_summary) + system_suffix,
    }
    result: DomainAnalysis = await chain.ainvoke(invoke_input)
    return {**state, "analysis": result, "retry_count": state["retry_count"] + 1}


def _validate(state: DomainAnalysisState) -> DomainAnalysisState:
    analysis = state["analysis"]
    ast_summary = state["ast_summary"]
    errors: list[str] = []

    if analysis is None:
        return {**state, "validation_errors": ["no analysis produced"]}

    ast_method_names = {m.name for fs in ast_summary.files for m in fs.methods}
    analysis_method_names = {m.method_name for m in analysis.methods}
    missing = ast_method_names - analysis_method_names
    if missing:
        errors.append(f"missing methods: {', '.join(sorted(missing))}")

    for m in analysis.methods:
        if not m.signature.strip():
            errors.append(f"empty signature for {m.method_name}")

    if analysis.complexity not in ("low", "medium", "high"):
        errors.append(f"invalid complexity: {analysis.complexity!r}")

    return {**state, "validation_errors": errors}


def _should_retry(state: DomainAnalysisState) -> str:
    if state["validation_errors"] and state["retry_count"] < 2:
        return "retry"
    if state["validation_errors"]:
        logger.warning(
            "Validation failed after max retries, returning best-effort result",
            extra={"domain": state["domain"], "errors": state["validation_errors"]},
        )
    return "done"


def _build_graph():
    graph = StateGraph(DomainAnalysisState)
    graph.add_node("ast_extract", _ast_extract)
    graph.add_node("llm_analyze", _llm_analyze)
    graph.add_node("validate", _validate)

    graph.set_entry_point("ast_extract")
    graph.add_edge("ast_extract", "llm_analyze")
    graph.add_edge("llm_analyze", "validate")
    graph.add_conditional_edges(
        "validate",
        _should_retry,
        {"retry": "llm_analyze", "done": END},
    )
    return graph.compile()


class PythonAnalyzer(LanguageAnalyzer):
    _graph = None

    @property
    def ext(self) -> str:
        return ".py"

    def _get_graph(self):
        if PythonAnalyzer._graph is None:
            PythonAnalyzer._graph = _build_graph()
        return PythonAnalyzer._graph

    def get_domain_map(self, source: Path) -> dict[str, list[Path]]:
        packages = [
            d for d in source.iterdir()
            if d.is_dir() and (d / "__init__.py").exists()
        ]
        if packages:
            domain_map: dict[str, list[Path]] = {}
            for pkg in sorted(packages):
                files = [
                    f for f in pkg.rglob("*.py")
                    if not any(seg in _SKIP_SEGMENTS for seg in f.parts)
                ]
                if files:
                    domain_map[pkg.name] = files
            return domain_map

        return FileLoader(source, self.ext).load()

    async def analyze_domain(
        self,
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
                logger.info(
                    "Domain analysis started",
                    extra={"domain": domain, "file_count": len(files)},
                )

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
                graph = self._get_graph()
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

                span.set_attribute("complexity", analysis.complexity)
                logger.info(
                    "Domain analysis complete",
                    extra={
                        "domain": domain,
                        "duration_ms": round((time.monotonic() - t0) * 1000),
                        "complexity": analysis.complexity,
                    },
                )
                return analysis, final_state["skipped_files"]
            except Exception as exc:
                span.record_exception(exc)
                span.set_status(StatusCode.ERROR, description=str(exc))
                raise

    def get_aggregation_prompt(self) -> ChatPromptTemplate:
        return PYTHON_AGGREGATION_PROMPT
