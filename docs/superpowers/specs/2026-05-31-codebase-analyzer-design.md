# Codebase Analyzer — Design Spec

**Date:** 2026-05-31  
**Status:** Approved

---

## Overview

A generic Python CLI tool that analyzes any Java codebase, extracts structured knowledge using a LangChain LCEL hierarchical LLM pipeline, and emits a machine-readable `output.json`. Demonstrated against the `spring-rest-sakila` project (200 Java files, 9 domain services).

**Invocation:**
```bash
python main.py --source ./spring-rest-sakila-main --output report.json
```

---

## Decisions

| Question | Choice | Rationale |
|---|---|---|
| Generic vs hardcoded | Generic (path arg) | Higher engineering value; works on any Java project |
| LLM provider | LangChain-abstracted | Swap Anthropic / OpenAI / Gemini via env var |
| Analysis strategy | Hierarchical (domain → project) | Token-efficient; natural output structure; scales to large repos |
| Caching | SHA256 disk cache | Skip re-analysis for unchanged domains; cost + speed |

---

## Project Structure

```
codebase-analysis/
├── src/
│   ├── __init__.py
│   ├── loader.py          # FileLoader: walks source tree, groups files by domain
│   ├── llm_factory.py     # init_chat_model wrapper + env var validation
│   ├── models.py          # Pydantic v2 output schemas
│   ├── prompts.py         # ChatPromptTemplates for extraction + aggregation
│   ├── pipeline.py        # LCEL chains + RunnableParallel orchestration
│   ├── cache.py           # SHA256-keyed JSON disk cache
│   └── cli.py             # Click CLI
├── tests/
│   ├── test_loader.py
│   ├── test_models.py
│   ├── test_pipeline.py
│   └── test_cache.py
├── main.py
├── pyproject.toml         # uv-managed deps + ruff config
├── Dockerfile             # multi-stage, python:3.13-slim + uv
├── docker-compose.yml
├── .env.example
└── README.md
```

---

## Dependencies

| Package | Version | Role |
|---|---|---|
| `langchain` | `>=0.3` | LCEL, `init_chat_model`, prompt templates |
| `langchain-anthropic` | `>=1.1.0` | Anthropic Claude backend |
| `langchain-openai` | latest | OpenAI backend |
| `langchain-google-genai` | latest | Google Gemini backend |
| `pydantic` | `>=2` | Output schema enforcement |
| `click` | latest | CLI interface |
| `tenacity` | latest | Retry with exponential backoff |
| `pytest` | dev | Testing |
| `pytest-asyncio` | dev | Async chain tests |
| `ruff` | dev | Linting (via `uv run ruff`) |

---

## Data Flow

```
CLI args
  │
  ▼
FileLoader
  - Recursively walks --source path
  - Filters by extension (.java default, configurable)
  - Groups files by domain via package path segment
    e.g. services/catalog/* → domain "catalog"
  - Returns: Dict[str, List[Path]]
  │
  ▼
Cache Check (per domain)
  - key = SHA256(sorted concatenation of file contents)
  - Hit  → load DomainAnalysis from .cache/<hash>.json
  - Miss → proceed to LLM
  │
  ▼
RunnableParallel — Domain Extraction (uncached domains only)
  For each domain concurrently:
    ChatPromptTemplate | llm.with_structured_output(DomainAnalysis)
  - Input:  domain name + concatenated file contents
  - Output: DomainAnalysis (Pydantic)
  - Writes result to .cache/<hash>.json on success
  │
  ▼
Aggregation Chain
  ChatPromptTemplate(all DomainAnalysis summaries)
    | llm.with_structured_output(ProjectReport)
  - Input:  serialized DomainAnalysis list (summaries only, not raw code)
  - Output: ProjectReport (Pydantic)
  │
  ▼
JSON Writer
  - Merges ProjectReport + domains list
  - Writes to --output path
```

---

## JSON Output Schema

```json
{
  "project": {
    "name": "string",
    "overview": "string",
    "purpose": "string",
    "tech_stack": ["string"],
    "architecture_pattern": "string"
  },
  "domains": [
    {
      "name": "string",
      "description": "string",
      "file_count": 0,
      "complexity": "low | medium | high",
      "methods": [
        {
          "class": "string",
          "method_name": "string",
          "signature": "string",
          "description": "string",
          "http_method": "GET | POST | PUT | DELETE | PATCH | null",
          "endpoint": "string | null",
          "complexity": "low | medium | high"
        }
      ],
      "notable_aspects": ["string"]
    }
  ],
  "summary": {
    "total_files": 0,
    "total_domains": 0,
    "total_methods": 0,
    "overall_complexity": "low | medium | high",
    "key_patterns": ["string"],
    "notable_aspects": ["string"],
    "skipped_files": ["string"]
  }
}
```

All three providers (Anthropic, OpenAI, Gemini) enforce this schema via `.with_structured_output(Model, method="json_schema")`.

---

## LLM Provider Configuration

Uses `langchain.chat_models.init_chat_model` — the modern provider-agnostic factory.

| `LLM_PROVIDER` value | Package required | API key env var |
|---|---|---|
| `anthropic` | `langchain-anthropic>=1.1.0` | `ANTHROPIC_API_KEY` |
| `openai` | `langchain-openai` | `OPENAI_API_KEY` |
| `google_genai` | `langchain-google-genai` | `GOOGLE_API_KEY` |

Default models: `claude-sonnet-4-6` / `gpt-4o` / `gemini-2.5-flash-lite`

```python
from langchain.chat_models import init_chat_model

llm = init_chat_model(f"{provider}:{model}", max_retries=3, temperature=0)
structured_llm = llm.with_structured_output(DomainAnalysis, method="json_schema")
```

---

## Caching Strategy

```
.cache/
  <sha256>.json    ← serialized DomainAnalysis
```

- **Key**: `SHA256(sorted file contents of all files in domain)`
- **Invalidation**: automatic — any change to any file in a domain busts its hash
- **Scope**: domain extraction only; aggregation pass is uncached (cheap: summaries, not raw code)
- **`--no-cache` flag**: disables all cache reads and writes
- `.cache/` is gitignored

---

## Error Handling

| Scenario | Behavior |
|---|---|
| LLM call fails | `tenacity` exponential backoff, 3 attempts, logged to stderr |
| Structured output malformed | LangChain retries internally; on final failure, domain entry contains `{"error": "..."}` |
| File unreadable | Skip + warn; path added to `summary.skipped_files` |
| Provider not configured | `click` fails immediately with message listing required env vars |
| All domains cached, aggregation fails | Partial output written; exit code 1 |

---

## Testing

- `test_loader.py` — domain grouping, extension filtering, empty dirs
- `test_models.py` — Pydantic schema validation, enum constraints, nullable fields
- `test_pipeline.py` — full pipeline using `FakeChatModel` (no API calls)
- `test_cache.py` — cache hit, cache miss, hash invalidation on file change

All tests use `FakeChatModel` — zero API cost. One integration test fixture (skipped if no API key in env) runs against a 5-file sample from `spring-rest-sakila-main`.

Run: `uv run pytest`

---

## Docker & Deployment

### Dockerfile (multi-stage)

```dockerfile
# Stage 1 — install deps with uv
FROM python:3.13-slim AS builder
RUN pip install uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Stage 2 — runtime
FROM python:3.13-slim
WORKDIR /app
COPY --from=builder /app/.venv .venv
COPY src/ src/
COPY main.py .
ENV PATH="/app/.venv/bin:$PATH"
ENTRYPOINT ["python", "main.py"]
```

### docker-compose.yml

```yaml
services:
  analyzer:
    build: .
    env_file: .env
    volumes:
      - ./spring-rest-sakila-main:/codebase:ro
      - ./output:/output
    command: ["--source", "/codebase", "--output", "/output/report.json"]
```

### .env.example

```bash
LLM_PROVIDER=anthropic
LLM_MODEL=claude-sonnet-4-6
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GOOGLE_API_KEY=AIza...
```

---

## CLI Interface

```
Usage: python main.py [OPTIONS]

Options:
  --source   PATH    Path to codebase root to analyze  [required]
  --output   PATH    Output JSON file path  [default: output.json]
  --provider TEXT    LLM provider: anthropic | openai | google_genai
                     (overrides LLM_PROVIDER env var)
  --model    TEXT    Model name (overrides LLM_MODEL env var)
  --no-cache         Disable disk cache
  --ext      TEXT    File extension filter  [default: .java]
  --help             Show this message and exit.
```

---

## Assumptions & Limitations

- **Language**: Optimized for Java; works for any language since analysis is LLM-based, but domain grouping heuristic assumes package-style directory structure
- **Token limits**: Domains with very large file sets are truncated at ~80k chars before sending to LLM; a warning is emitted
- **Cost**: A full run on 200 Java files with no cache costs approximately 500k–1M tokens depending on provider; caching makes subsequent runs near-free
- **No database**: All state lives in `.cache/` JSON files and the output JSON; no external services required
