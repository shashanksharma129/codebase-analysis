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
