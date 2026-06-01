import asyncio
import logging
from pathlib import Path

from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from opentelemetry import trace
from opentelemetry.trace import StatusCode

from src.analyzers.base import LanguageAnalyzer
from src.cache import Cache
from src.models import DomainAnalysis, FinalOutput, ProjectReport, ProjectSummary

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


async def _run_aggregation(
    domain_results: list[DomainAnalysis],
    llm: BaseChatModel,
    aggregation_prompt: ChatPromptTemplate,
) -> ProjectReport:
    with tracer.start_as_current_span(
        "run_aggregation",
        attributes={"domain_count": len(domain_results)},
    ) as span:
        try:
            summaries = "\n\n".join(
                f"=== {d.name} ===\n{d.model_dump_json(indent=2)}" for d in domain_results
            )
            chain = aggregation_prompt | llm.with_structured_output(
                ProjectReport, method="json_schema"
            )
            result = await chain.ainvoke({"domain_summaries": summaries})
            total_methods = sum(len(d.methods) for d in domain_results)
            span.set_attribute("total_methods", total_methods)
            span.set_attribute("overall_complexity", result.summary.overall_complexity)
            logger.info(
                "Aggregation complete",
                extra={
                    "domain_count": len(domain_results),
                    "total_methods": total_methods,
                    "overall_complexity": result.summary.overall_complexity,
                },
            )
            return result
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(StatusCode.ERROR, description=str(exc))
            raise


async def run_pipeline(
    source: Path,
    llm: BaseChatModel,
    cache: Cache | None,
    analyzer: LanguageAnalyzer,
) -> FinalOutput:
    with tracer.start_as_current_span("run_pipeline") as span:
        try:
            domains = analyzer.get_domain_map(source)

            span.set_attribute("domain_count", len(domains))
            span.set_attribute("total_files", sum(len(f) for f in domains.values()))
            span.set_attribute("language", analyzer.ext.lstrip("."))

            if not domains:
                report = await _run_aggregation([], llm, analyzer.get_aggregation_prompt())
                return FinalOutput(
                    language=analyzer.ext.lstrip("."),
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
                analyzer.analyze_domain(name, files, llm, cache)
                for name, files in domains.items()
            ]
            gathered = await asyncio.gather(*tasks)
            domain_tuples: list[tuple[DomainAnalysis, list[str]]] = list(gathered)
            domain_results = [d for d, _ in domain_tuples]
            all_skipped = [p for _, skipped in domain_tuples for p in skipped]

            report = await _run_aggregation(domain_results, llm, analyzer.get_aggregation_prompt())

            return FinalOutput(
                language=analyzer.ext.lstrip("."),
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
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(StatusCode.ERROR, description=str(exc))
            raise
