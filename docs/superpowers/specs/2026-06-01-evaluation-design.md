# Evaluation System Design

## Goal

Add a golden-fixture offline evaluation harness that measures LLM output quality on method extraction, HTTP metadata accuracy, and complexity scoring. Runs against real LLM calls by default; replays saved results in CI.

## Architecture

All evaluation code lives in a top-level `evals/` package. It is intentionally separate from `src/` — evals are not production code and should never be imported by the application.

```
evals/
  __main__.py          # entry point: python -m evals [--replay] [--fixture NAME]
  metrics.py           # pure scoring functions: recall, precision, http_accuracy
  runner.py            # orchestrates fixtures → analyze/replay → score → report
  fixtures/
    actor/
      input/           # .java source files from spring-rest-sakila
      expected.json    # hand-reviewed DomainAnalysis JSON (ground truth)
    film/
      input/
      expected.json
  results/             # gitignored — saved LLM outputs from real runs
tests/
  test_metrics.py      # unit tests for all scoring functions
```

`evals/results/` is gitignored. It holds live LLM outputs that change on every real run. `evals/fixtures/` is committed — it is the deliberate ground truth that changes only when a human reviews and approves a change.

## Fixtures

Two fixtures sourced from `spring-rest-sakila-main/`:

- **actor** — simple CRUD domain (`ActorController`, `ActorService`, `ActorRepository`). Tests baseline method recall and HTTP extraction on straightforward GET/POST/PUT/DELETE endpoints.
- **film** — more complex domain with joins, pagination, and service-layer logic. Tests complexity scoring and edge cases like methods with no HTTP mapping.

Each fixture directory:
```
fixtures/<name>/
  input/          one or more .java files (copied verbatim)
  expected.json   a valid DomainAnalysis JSON, hand-reviewed for correctness
```

`expected.json` is produced by running the analyzer once, then manually reviewing and correcting the output — not written from scratch. The human review step is what makes it ground truth.

## Metrics

All metrics are computed in `evals/metrics.py` as pure functions with no I/O.

### Method Recall
```
recall = |found ∩ expected| / |expected|
```
Fraction of expected methods the LLM found. Names are normalized before comparison: lowercased, underscores and spaces stripped. This absorbs LLM paraphrasing (e.g. `getActor` vs `get_actor`).

### Method Precision
```
precision = |found ∩ expected| / |found|
```
Fraction of found methods that were expected. High precision with low recall means the LLM is being conservative. Low precision means it is hallucinating methods.

### HTTP Accuracy
Only computed for fixtures that have methods with non-null `http_method` in `expected.json`.
```
http_accuracy = methods where (verb matches AND endpoint matches) / methods with expected http_method
```
Both `http_method` and `endpoint` must match exactly (endpoint comparison is case-insensitive, trailing slash ignored).

### Pass Thresholds

| Metric | Pass threshold |
|---|---|
| Method recall | ≥ 0.85 |
| Method precision | ≥ 0.75 |
| HTTP accuracy | ≥ 0.90 (only if fixture has HTTP endpoints) |

The process exits with code 1 if any fixture fails any applicable threshold. CI reads exit codes, not stdout.

## Runner Modes

### Default — real LLM
```bash
python -m evals
```
Calls `JavaAnalyzer.analyze_domain()` for each fixture using the configured LLM (reads `LLM_PROVIDER` / `LLM_MODEL` / API key from environment). Saves raw `DomainAnalysis` output to `evals/results/<fixture>.json`. Scores against `expected.json`. Prints report.

### Replay — no LLM call
```bash
python -m evals --replay
```
Loads from `evals/results/<fixture>.json` (must exist from a prior real run). Scores and prints. Fast, free, deterministic. This is the mode CI runs.

### Single fixture
```bash
python -m evals --fixture actor
```
Runs (or replays) only the named fixture.

## Report Format

```
fixture       recall   precision   http_acc   status
──────────────────────────────────────────────────────
actor          0.92      0.88        1.00      PASS
film           0.79      0.95        0.83      FAIL
──────────────────────────────────────────────────────
overall                                        FAIL
```

`FAIL` lines print to stderr. Exit code is 0 if all fixtures pass, 1 otherwise.

## Error Handling

- **Missing results file in replay mode** — print a clear error: `"No saved result for fixture 'actor'. Run without --replay first."` Exit 1.
- **LLM call fails during real run** — print the error, mark fixture as ERROR (not FAIL), continue to next fixture. Exit 1 at the end if any fixture errored.
- **expected.json fails Pydantic validation** — raise immediately with a clear message. A malformed fixture is a bug in the test data, not a model failure.

## Files Changed

- **Create:** `evals/__main__.py`
- **Create:** `evals/metrics.py`
- **Create:** `evals/runner.py`
- **Create:** `evals/fixtures/actor/input/*.java` (copied from spring-rest-sakila-main)
- **Create:** `evals/fixtures/actor/expected.json`
- **Create:** `evals/fixtures/film/input/*.java`
- **Create:** `evals/fixtures/film/expected.json`
- **Create:** `tests/test_metrics.py`
- **Modify:** `.gitignore` — add `evals/results/`
