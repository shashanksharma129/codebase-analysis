import asyncio
import sys
from pathlib import Path

from evals.metrics import http_accuracy, method_precision, method_recall
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
