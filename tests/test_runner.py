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
