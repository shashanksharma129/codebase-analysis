import asyncio
import logging
import os
import time
from pathlib import Path

import click
from opentelemetry import trace
from opentelemetry.trace import StatusCode

from src.analyzers import get_analyzer
from src.cache import create_cache
from src.llm_factory import create_llm
from src.observability import setup_telemetry
from src.pipeline import run_pipeline

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


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
    "--language",
    default="java",
    type=click.Choice(["java", "python"]),
    show_default=True,
    help="Language of the codebase to analyze.",
)
def analyze(
    source: Path,
    output: Path,
    provider: str | None,
    model: str | None,
    no_cache: bool,
    language: str,
) -> None:
    """Analyze a codebase and extract structured knowledge to JSON."""
    setup_telemetry()
    llm = create_llm(provider, model)
    cache = None if no_cache else create_cache()
    _ext_map = {"java": ".java", "python": ".py"}
    analyzer = get_analyzer(_ext_map[language])

    # must mirror default-resolution logic in llm_factory.py
    resolved_provider = provider or os.environ.get("LLM_PROVIDER", "anthropic")
    with tracer.start_as_current_span(
        "analyze_repo",
        attributes={"repo": str(source), "provider": resolved_provider, "language": language},
    ) as span:
        try:
            logger.info(
                "analyze starting",
                extra={"source": str(source), "provider": resolved_provider, "language": language},
            )
            t0 = time.monotonic()
            result = asyncio.run(run_pipeline(source, llm, cache, analyzer))
            duration_ms = round((time.monotonic() - t0) * 1000)

            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(result.model_dump_json(indent=2, by_alias=True))
            logger.info(
                "Analysis complete",
                extra={"output_path": str(output), "duration_ms": duration_ms},
            )
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(StatusCode.ERROR, description=str(exc))
            raise
