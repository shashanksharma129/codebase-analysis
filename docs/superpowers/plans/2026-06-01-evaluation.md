# Evaluation System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a golden-fixture offline eval harness that scores LLM output quality on method recall, precision, and HTTP metadata accuracy, with real-LLM and replay modes.

**Architecture:** `evals/` package separate from `src/`. Pure scoring functions in `metrics.py`, orchestration in `runner.py`, thin CLI in `__main__.py`. Fixtures in `evals/fixtures/<name>/` (committed); saved LLM results in `evals/results/` (gitignored). Replay mode loads saved results for fast, free CI runs.

**Tech Stack:** Python stdlib (`asyncio`, `argparse`, `json`), Pydantic (`DomainAnalysis`, `MethodInfo` from `src.models`), `src.analyzers.java.JavaAnalyzer`, `src.llm_factory.create_llm`

---

## File Structure

```
evals/
  __init__.py          empty — makes evals a package
  __main__.py          CLI entry point: python -m evals [--replay] [--fixture NAME]
  metrics.py           pure scoring functions: method_recall, method_precision, http_accuracy
  runner.py            load_fixture, score_fixture, run_evals, print_report
  fixtures/
    actor/
      input/           ActorController.java, ActorServiceImpl.java
      expected.json    hand-reviewed DomainAnalysis JSON
    film/
      input/           FilmController.java, FilmServiceImpl.java
      expected.json    hand-reviewed DomainAnalysis JSON
  results/             gitignored — DomainAnalysis JSON from real LLM runs
tests/
  test_metrics.py      unit tests for all scoring functions
  test_runner.py       unit tests for score_fixture pass/fail logic
```

---

## Task 1: `evals/metrics.py` + `tests/test_metrics.py`

**Files:**
- Create: `evals/__init__.py`
- Create: `evals/metrics.py`
- Create: `tests/test_metrics.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_metrics.py`:

```python
import pytest
from src.models import MethodInfo
from evals.metrics import method_recall, method_precision, http_accuracy


def _m(name: str, verb: str | None = None, path: str | None = None) -> MethodInfo:
    return MethodInfo(
        class_name="Foo",
        method_name=name,
        signature=f"void {name}()",
        description="desc",
        http_method=verb,
        endpoint=path,
        complexity="low",
    )


# ── method_recall ─────────────────────────────────────────────────────────────

def test_recall_perfect():
    assert method_recall(["getActor", "createActor"], ["getActor", "createActor"]) == 1.0


def test_recall_partial():
    result = method_recall(["getActor", "createActor", "deleteActor"], ["getActor", "createActor"])
    assert result == pytest.approx(2 / 3)


def test_recall_empty_expected():
    assert method_recall([], ["getActor"]) == 1.0


def test_recall_case_insensitive():
    assert method_recall(["getActor"], ["GetActor"]) == 1.0


def test_recall_underscore_normalized():
    assert method_recall(["get_actor"], ["getActor"]) == 1.0


def test_recall_nothing_found():
    assert method_recall(["getActor", "createActor"], []) == 0.0


# ── method_precision ──────────────────────────────────────────────────────────

def test_precision_perfect():
    assert method_precision(["getActor"], ["getActor"]) == 1.0


def test_precision_hallucination():
    result = method_precision(["getActor"], ["getActor", "fakeMethod"])
    assert result == pytest.approx(0.5)


def test_precision_empty_found():
    assert method_precision(["getActor"], []) == 1.0


# ── http_accuracy ─────────────────────────────────────────────────────────────

def test_http_accuracy_no_http_in_expected():
    assert http_accuracy([_m("helper")], [_m("helper")]) is None


def test_http_accuracy_perfect():
    expected = [_m("getActor", "GET", "/actors/{id}")]
    found = [_m("getActor", "GET", "/actors/{id}")]
    assert http_accuracy(expected, found) == 1.0


def test_http_accuracy_wrong_verb():
    expected = [_m("getActor", "GET", "/actors/{id}")]
    found = [_m("getActor", "POST", "/actors/{id}")]
    assert http_accuracy(expected, found) == 0.0


def test_http_accuracy_wrong_endpoint():
    expected = [_m("getActor", "GET", "/actors/{id}")]
    found = [_m("getActor", "GET", "/actors")]
    assert http_accuracy(expected, found) == 0.0


def test_http_accuracy_method_not_found():
    expected = [_m("getActor", "GET", "/actors/{id}")]
    assert http_accuracy(expected, []) == 0.0


def test_http_accuracy_trailing_slash_ignored():
    expected = [_m("getActor", "GET", "/actors/{id}/")]
    found = [_m("getActor", "GET", "/actors/{id}")]
    assert http_accuracy(expected, found) == 1.0


def test_http_accuracy_partial():
    expected = [
        _m("getActor", "GET", "/actors/{id}"),
        _m("createActor", "POST", "/actors"),
    ]
    found = [
        _m("getActor", "GET", "/actors/{id}"),
        _m("createActor", "POST", "/wrong"),
    ]
    assert http_accuracy(expected, found) == pytest.approx(0.5)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_metrics.py -v
```

Expected: `ModuleNotFoundError: No module named 'evals'`

- [ ] **Step 3: Create `evals/__init__.py`**

```python
```

(Empty file — just makes `evals` a package.)

- [ ] **Step 4: Create `evals/metrics.py`**

```python
from src.models import MethodInfo


def _normalize(name: str) -> str:
    return name.lower().replace("_", "").replace(" ", "")


def method_recall(expected_names: list[str], found_names: list[str]) -> float:
    if not expected_names:
        return 1.0
    exp = {_normalize(n) for n in expected_names}
    fnd = {_normalize(n) for n in found_names}
    return len(exp & fnd) / len(exp)


def method_precision(expected_names: list[str], found_names: list[str]) -> float:
    if not found_names:
        return 1.0
    exp = {_normalize(n) for n in expected_names}
    fnd = {_normalize(n) for n in found_names}
    return len(exp & fnd) / len(fnd)


def http_accuracy(
    expected_methods: list[MethodInfo],
    found_methods: list[MethodInfo],
) -> float | None:
    expected_http = [m for m in expected_methods if m.http_method]
    if not expected_http:
        return None
    found_by_name = {_normalize(m.method_name): m for m in found_methods}
    matches = 0
    for exp in expected_http:
        found = found_by_name.get(_normalize(exp.method_name))
        if found is None:
            continue
        verb_ok = found.http_method == exp.http_method
        endpoint_ok = (
            (found.endpoint or "").rstrip("/").lower()
            == (exp.endpoint or "").rstrip("/").lower()
        )
        if verb_ok and endpoint_ok:
            matches += 1
    return matches / len(expected_http)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
python -m pytest tests/test_metrics.py -v
```

Expected: all 16 tests pass.

- [ ] **Step 6: Commit**

```bash
git add evals/__init__.py evals/metrics.py tests/test_metrics.py
git commit -m "feat: add eval metrics (recall, precision, http_accuracy) with tests"
```

---

## Task 2: Actor fixture — copy Java source files

**Files:**
- Create: `evals/fixtures/actor/input/ActorController.java`
- Create: `evals/fixtures/actor/input/ActorServiceImpl.java`

The fixture contains two files: the controller (HTTP endpoints) and the service implementation (business logic methods). Together they define the complete expected method surface for the `"actor"` domain.

- [ ] **Step 1: Create the fixture input directory and copy files**

```bash
mkdir -p evals/fixtures/actor/input

cp spring-rest-sakila-main/spring-rest-sakila-main/src/main/java/com/example/app/services/catalog/controller/ActorController.java \
   evals/fixtures/actor/input/

cp spring-rest-sakila-main/spring-rest-sakila-main/src/main/java/com/example/app/services/catalog/service/ActorServiceImpl.java \
   evals/fixtures/actor/input/
```

- [ ] **Step 2: Verify files are in place**

```bash
ls evals/fixtures/actor/input/
```

Expected:
```
ActorController.java
ActorServiceImpl.java
```

- [ ] **Step 3: Commit**

```bash
git add evals/fixtures/actor/input/
git commit -m "feat: add actor fixture Java source files"
```

---

## Task 3: Generate and review actor `expected.json`

**Files:**
- Create: `evals/fixtures/actor/expected.json`

`expected.json` is a `DomainAnalysis` JSON produced by running the real LLM once, then manually reviewed for correctness. The human review step is what makes it ground truth.

- [ ] **Step 1: Generate candidate `expected.json` using the real LLM**

```bash
python -c "
import asyncio
from pathlib import Path
from src.analyzers.java import JavaAnalyzer
from src.llm_factory import create_llm

async def main():
    llm = create_llm()
    files = sorted(Path('evals/fixtures/actor/input').glob('*.java'))
    result, skipped = await JavaAnalyzer().analyze_domain('actor', files, llm, None)
    print(result.model_dump_json(indent=2, by_alias=True))

asyncio.run(main())
" > evals/fixtures/actor/expected.json
```

- [ ] **Step 2: Review the generated file**

Open `evals/fixtures/actor/expected.json` and check each method entry against the Java source files:

- Open `evals/fixtures/actor/input/ActorController.java` and list every public method. Verify each appears in `expected.json` with the correct `http_method` (GET/POST/PUT/DELETE) and `endpoint` path.
- Open `evals/fixtures/actor/input/ActorServiceImpl.java` and list every public method. Verify each appears in `expected.json` with `http_method: null`.
- Fix any incorrect `http_method`, `endpoint`, or missing methods by editing `evals/fixtures/actor/expected.json` directly.
- Verify `"complexity"` at the domain level is `"low"`, `"medium"`, or `"high"`.

- [ ] **Step 3: Commit**

```bash
git add evals/fixtures/actor/expected.json
git commit -m "feat: add actor fixture expected.json (hand-reviewed ground truth)"
```

---

## Task 4: `evals/runner.py` + `evals/__main__.py` + `tests/test_runner.py`

**Files:**
- Create: `evals/runner.py`
- Create: `evals/__main__.py`
- Create: `tests/test_runner.py`

- [ ] **Step 1: Write the failing tests for `score_fixture`**

Create `tests/test_runner.py`:

```python
import pytest
from src.models import DomainAnalysis, MethodInfo
from evals.runner import score_fixture


def _make_method(name: str, verb: str | None = None, path: str | None = None) -> MethodInfo:
    return MethodInfo(
        class_name="Foo",
        method_name=name,
        signature=f"void {name}()",
        description="desc",
        http_method=verb,
        endpoint=path,
        complexity="low",
    )


def _make_domain(methods: list[MethodInfo]) -> DomainAnalysis:
    return DomainAnalysis(
        name="test",
        description="desc",
        file_count=1,
        complexity="low",
        methods=methods,
        notable_aspects=[],
    )


def test_score_fixture_perfect_pass():
    expected = _make_domain([_make_method("getActor", "GET", "/actors/{id}")])
    result = _make_domain([_make_method("getActor", "GET", "/actors/{id}")])
    scores = score_fixture(result, expected)
    assert scores["recall"] == 1.0
    assert scores["precision"] == 1.0
    assert scores["http_acc"] == 1.0
    assert scores["status"] == "PASS"


def test_score_fixture_fail_low_recall():
    expected = _make_domain([
        _make_method("a"), _make_method("b"), _make_method("c"), _make_method("d"),
    ])
    result = _make_domain([_make_method("a")])  # recall = 0.25 < 0.85
    scores = score_fixture(result, expected)
    assert scores["recall"] == pytest.approx(0.25)
    assert scores["status"] == "FAIL"


def test_score_fixture_fail_low_precision():
    expected = _make_domain([_make_method("getActor")])
    result = _make_domain([
        _make_method("getActor"),
        _make_method("fake1"),
        _make_method("fake2"),
        _make_method("fake3"),
    ])  # precision = 1/4 = 0.25 < 0.75
    scores = score_fixture(result, expected)
    assert scores["precision"] == pytest.approx(0.25)
    assert scores["status"] == "FAIL"


def test_score_fixture_fail_low_http_accuracy():
    expected = _make_domain([_make_method("getActor", "GET", "/actors/{id}")])
    result = _make_domain([_make_method("getActor", "POST", "/wrong")])  # http_acc = 0.0 < 0.90
    scores = score_fixture(result, expected)
    assert scores["http_acc"] == 0.0
    assert scores["status"] == "FAIL"


def test_score_fixture_no_http_endpoints():
    expected = _make_domain([_make_method("helper")])
    result = _make_domain([_make_method("helper")])
    scores = score_fixture(result, expected)
    assert scores["http_acc"] is None
    assert scores["status"] == "PASS"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_runner.py -v
```

Expected: `ImportError: cannot import name 'score_fixture' from 'evals.runner'`

- [ ] **Step 3: Create `evals/runner.py`**

```python
import asyncio
import json
import sys
from pathlib import Path

from src.analyzers.java import JavaAnalyzer
from src.llm_factory import create_llm
from src.models import DomainAnalysis
from evals.metrics import http_accuracy, method_precision, method_recall

FIXTURES_DIR = Path("evals/fixtures")
RESULTS_DIR = Path("evals/results")

_PASS_RECALL = 0.85
_PASS_PRECISION = 0.75
_PASS_HTTP = 0.90


def load_fixture(name: str, fixtures_dir: Path = FIXTURES_DIR) -> tuple[list[Path], DomainAnalysis]:
    fixture_dir = fixtures_dir / name
    input_files = sorted((fixture_dir / "input").glob("*.java"))
    expected = DomainAnalysis.model_validate_json(
        (fixture_dir / "expected.json").read_text()
    )
    return input_files, expected


def score_fixture(result: DomainAnalysis, expected: DomainAnalysis) -> dict:
    expected_names = [m.method_name for m in expected.methods]
    found_names = [m.method_name for m in result.methods]
    recall = method_recall(expected_names, found_names)
    precision = method_precision(expected_names, found_names)
    http_acc = http_accuracy(expected.methods, result.methods)

    status = "PASS"
    if recall < _PASS_RECALL:
        status = "FAIL"
    if precision < _PASS_PRECISION:
        status = "FAIL"
    if http_acc is not None and http_acc < _PASS_HTTP:
        status = "FAIL"

    return {"recall": recall, "precision": precision, "http_acc": http_acc, "status": status}


def _print_report(rows: list[tuple[str, dict]]) -> None:
    header = f"{'fixture':<14}  {'recall':>7}  {'precision':>9}  {'http_acc':>8}  {'status':<6}"
    sep = "─" * len(header)
    print(header)
    print(sep)
    for name, scores in rows:
        http = f"{scores['http_acc']:.2f}" if scores["http_acc"] is not None else " N/A"
        line = (
            f"{name:<14}  {scores['recall']:>7.2f}  {scores['precision']:>9.2f}"
            f"  {http:>8}  {scores['status']:<6}"
        )
        if scores["status"] == "FAIL":
            print(line, file=sys.stderr)
        else:
            print(line)
    print(sep)
    overall = "PASS" if all(s["status"] == "PASS" for _, s in rows) else "FAIL"
    print(f"{'overall':<14}  {'':>7}  {'':>9}  {'':>8}  {overall:<6}")


def run_evals(
    replay: bool = False,
    fixture: str | None = None,
    fixtures_dir: Path = FIXTURES_DIR,
    results_dir: Path = RESULTS_DIR,
) -> bool:
    fixture_names = (
        [fixture]
        if fixture
        else sorted(d.name for d in fixtures_dir.iterdir() if d.is_dir())
    )

    llm = None if replay else create_llm()
    results_dir.mkdir(parents=True, exist_ok=True)

    rows: list[tuple[str, dict]] = []
    all_passed = True

    for name in fixture_names:
        try:
            input_files, expected = load_fixture(name, fixtures_dir)
        except FileNotFoundError as e:
            print(f"ERROR: fixture '{name}' missing file: {e}", file=sys.stderr)
            all_passed = False
            continue

        result_path = results_dir / f"{name}.json"

        if replay:
            if not result_path.exists():
                print(
                    f"ERROR: no saved result for fixture '{name}'. Run without --replay first.",
                    file=sys.stderr,
                )
                all_passed = False
                continue
            result = DomainAnalysis.model_validate_json(result_path.read_text())
        else:
            try:
                result, _ = asyncio.run(
                    JavaAnalyzer().analyze_domain(name, input_files, llm, None)
                )
                result_path.write_text(result.model_dump_json(indent=2, by_alias=True))
            except Exception as e:
                print(f"ERROR: LLM call failed for fixture '{name}': {e}", file=sys.stderr)
                all_passed = False
                continue

        scores = score_fixture(result, expected)
        if scores["status"] == "FAIL":
            all_passed = False
        rows.append((name, scores))

    _print_report(rows)
    return all_passed
```

- [ ] **Step 4: Create `evals/__main__.py`**

```python
import argparse
import sys

from evals.runner import run_evals


def main() -> None:
    parser = argparse.ArgumentParser(description="Run golden-fixture evals")
    parser.add_argument("--replay", action="store_true", help="Score saved results, no LLM call")
    parser.add_argument("--fixture", default=None, help="Run only this fixture (e.g. 'actor')")
    args = parser.parse_args()
    passed = run_evals(replay=args.replay, fixture=args.fixture)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
python -m pytest tests/test_runner.py -v
```

Expected: all 5 tests pass.

- [ ] **Step 6: Run full test suite to check nothing is broken**

```bash
python -m pytest -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add evals/runner.py evals/__main__.py tests/test_runner.py
git commit -m "feat: add eval runner with real-LLM and replay modes"
```

---

## Task 5: Film fixture — copy files and generate `expected.json`

**Files:**
- Create: `evals/fixtures/film/input/FilmController.java`
- Create: `evals/fixtures/film/input/FilmServiceImpl.java`
- Create: `evals/fixtures/film/expected.json`

- [ ] **Step 1: Copy film Java source files**

```bash
mkdir -p evals/fixtures/film/input

cp spring-rest-sakila-main/spring-rest-sakila-main/src/main/java/com/example/app/services/catalog/controller/FilmController.java \
   evals/fixtures/film/input/

cp spring-rest-sakila-main/spring-rest-sakila-main/src/main/java/com/example/app/services/catalog/service/FilmServiceImpl.java \
   evals/fixtures/film/input/
```

- [ ] **Step 2: Generate candidate `expected.json`**

```bash
python -c "
import asyncio
from pathlib import Path
from src.analyzers.java import JavaAnalyzer
from src.llm_factory import create_llm

async def main():
    llm = create_llm()
    files = sorted(Path('evals/fixtures/film/input').glob('*.java'))
    result, skipped = await JavaAnalyzer().analyze_domain('film', files, llm, None)
    print(result.model_dump_json(indent=2, by_alias=True))

asyncio.run(main())
" > evals/fixtures/film/expected.json
```

- [ ] **Step 3: Review the generated file**

Open `evals/fixtures/film/expected.json` and check:

- Open `evals/fixtures/film/input/FilmController.java` and verify every public HTTP handler method appears with the correct verb and endpoint path.
- Open `evals/fixtures/film/input/FilmServiceImpl.java` and verify every public method appears with `http_method: null`.
- Fix any errors directly in `evals/fixtures/film/expected.json`.

- [ ] **Step 4: Commit**

```bash
git add evals/fixtures/film/
git commit -m "feat: add film fixture with Java source files and expected.json"
```

---

## Task 6: Gitignore + end-to-end smoke test

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Add `evals/results/` to `.gitignore`**

Open `.gitignore` and add after the existing `# Project-specific` section:

```
# Eval harness — saved LLM outputs (replay sources, not ground truth)
evals/results/
```

- [ ] **Step 2: Verify gitignore is working**

```bash
mkdir -p evals/results && touch evals/results/test.json
git status
```

Expected: `evals/results/test.json` does NOT appear in `git status` output. Then clean up:

```bash
rm evals/results/test.json
```

- [ ] **Step 3: Run end-to-end real-LLM eval on actor fixture only**

```bash
python -m evals --fixture actor
```

Expected: runs the real LLM, prints a score table, creates `evals/results/actor.json`, exits 0 if recall ≥ 0.85, precision ≥ 0.75, and http_acc ≥ 0.90.

If it exits 1 (scores too low), open `evals/results/actor.json` and compare the extracted methods against `evals/fixtures/actor/expected.json`. If the expected.json has errors (wrong method name, wrong endpoint), fix `expected.json` and re-run. Do NOT lower the thresholds.

- [ ] **Step 4: Run replay mode to verify it works without LLM**

```bash
python -m evals --replay --fixture actor
```

Expected: prints same score table as Step 3, exits with same code, no LLM call.

- [ ] **Step 5: Run full test suite one final time**

```bash
python -m pytest -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add .gitignore
git commit -m "feat: gitignore evals/results and verify end-to-end eval pipeline"
```
