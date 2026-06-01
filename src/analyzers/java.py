import logging
import time
from pathlib import Path

from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from opentelemetry import trace
from opentelemetry.trace import StatusCode

from src.analyzers.base import LanguageAnalyzer
from src.cache import Cache
from src.loader import FileLoader
from src.models import DomainAnalysis
from src.prompts import AGGREGATION_PROMPT, EXTRACTION_PROMPT

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

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


class JavaAnalyzer(LanguageAnalyzer):

    @property
    def ext(self) -> str:
        return ".java"

    def get_domain_map(self, source: Path) -> dict[str, list[Path]]:
        return FileLoader(source, self.ext).load()

    async def analyze_domain(
        self,
        domain: str,
        files: list[Path],
        llm: BaseChatModel,
        cache: Cache | None,
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
                source, skipped = _read_domain(files)
                chain = EXTRACTION_PROMPT | llm.with_structured_output(
                    DomainAnalysis, method="json_schema"
                )
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
                span.set_status(StatusCode.ERROR, description=str(exc))
                raise

    def get_aggregation_prompt(self) -> ChatPromptTemplate:
        return AGGREGATION_PROMPT
