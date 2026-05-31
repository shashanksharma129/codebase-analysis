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
