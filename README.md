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

## Cloud Run Deployment

The Streamlit UI is deployed to GCP Cloud Run via Cloud Build.

### One-time setup

See `docs/superpowers/plans/2026-06-01-cloud-run-deployment.md` for the full
`gcloud` commands to run once: enable APIs, create the Artifact Registry repo,
GCS cache bucket, service account, IAM bindings, and Secret Manager entry.

After running those commands, connect Cloud Build to your GitHub repo:
**Cloud Build → Triggers → Connect Repository → GitHub** → select repo →
build config: `cloudbuild.yaml`, branch: `^main$`.

### Pipeline

Every push to `main` triggers Cloud Build, which:

1. Runs `pytest` (fast, no LLM calls)
2. Builds the Docker image and pushes to Artifact Registry
3. Deploys to Cloud Run (zero-downtime rolling update)

### Cache

On Cloud Run, the `GCS_CACHE_BUCKET=codebase-analysis-cache` env var activates
`GcsCache` instead of `DiskCache`. Cached analyses persist across container
restarts and scale-out instances. Locally, `DiskCache` is used as before
(no `GCS_CACHE_BUCKET` env var).

### Secrets

`GOOGLE_API_KEY` is stored in Secret Manager (`google-api-key`) and injected
as an env var at runtime. Never put API keys in `cloudbuild.yaml` or env vars
visible in the Cloud Run console.

## Evaluation

The `evals/` package is an offline quality harness that measures how accurately the LLM extracts method names, HTTP endpoints, and complexity from real Java source files.

### What it tests

Three metrics are computed against hand-reviewed ground truth (`evals/fixtures/<name>/expected.json`):

| Metric | Formula | Pass threshold |
|---|---|---|
| **Method recall** | `found ∩ expected / expected` | ≥ 0.85 |
| **Method precision** | `found ∩ expected / found` | ≥ 0.75 |
| **HTTP accuracy** | methods where verb AND path match / methods with expected HTTP | ≥ 0.90 |

Recall measures whether the LLM missed any methods. Precision measures whether it hallucinated extra ones. HTTP accuracy only applies to fixtures that have annotated endpoints.

Two fixtures are included:

- **actor** — simple CRUD domain (`ActorController` + `ActorServiceImpl`); 12 HTTP handlers, 13 service methods. Tests baseline method recall and HTTP extraction.
- **film** — more complex domain with caching, pagination, and HATEOAS; 8 HTTP handlers, 11 service methods with overloads. Tests edge cases like overloaded method names.

### Running

**Real LLM run** (requires API key in `.env`):
```bash
python -m evals                     # run all fixtures
python -m evals --fixture actor     # run one fixture
```

Saves LLM output to `evals/results/<name>.json` for later replay.

**Replay mode** (no LLM call, fast, used in CI):
```bash
python -m evals --replay
python -m evals --replay --fixture actor
```

Loads the saved result from a prior real run and rescores it. Exits 0 if all fixtures pass, 1 otherwise.

### How it works

```
evals/fixtures/<name>/input/*.java   ← Java source files (committed)
evals/fixtures/<name>/expected.json  ← hand-reviewed DomainAnalysis JSON (committed)
evals/results/<name>.json            ← saved LLM output from real runs (gitignored)
```

The ground truth in `expected.json` was produced by running the LLM once and then manually reviewing and correcting each method entry against the Java source. That human review step is what makes it ground truth — it is not auto-generated.

Name comparison is normalized (lowercased, underscores and spaces stripped) to absorb stylistic differences like `getActor` vs `get_actor`.

## Assumptions & Limitations

- Domain grouping works best with package-style layouts (`services/`, `modules/`, etc.)
- Domains exceeding 80 000 characters of source are truncated; a `// [truncated]` marker is added
- The aggregation pass is not cached (it only receives summaries, not raw code, so it's fast)
- A full run on the 200-file spring-rest-sakila project costs ~500k–1M tokens depending on provider
