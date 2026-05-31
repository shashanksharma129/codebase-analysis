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
