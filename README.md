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

## Web UI

A browser-based interface that accepts a public GitHub repository URL and displays results in two tabs — a human-readable summary and a raw JSON viewer with download.

```bash
cp .env.example .env        # fill in LLM_PROVIDER and matching API key
uv sync
streamlit run ui.py
```

Open `http://localhost:8501` in your browser, paste a GitHub URL (e.g. `https://github.com/codejsha/spring-rest-sakila`), and click **Analyze**.

> **Note:** Only public repositories are supported (no authentication).

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
