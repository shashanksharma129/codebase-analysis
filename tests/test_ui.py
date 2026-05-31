# tests/test_ui.py
import pytest

from src.models import DomainAnalysis, MethodInfo
from src.ui_helpers import _collect_endpoints
from ui import parse_github_url


def test_parse_simple_url():
    owner, repo, branch = parse_github_url("https://github.com/owner/repo")
    assert owner == "owner"
    assert repo == "repo"
    assert branch == "main"


def test_parse_url_with_branch():
    owner, repo, branch = parse_github_url("https://github.com/owner/repo/tree/develop")
    assert owner == "owner"
    assert repo == "repo"
    assert branch == "develop"


def test_parse_url_with_git_suffix():
    owner, repo, branch = parse_github_url("https://github.com/owner/repo.git")
    assert owner == "owner"
    assert repo == "repo"
    assert branch == "main"


def test_parse_url_with_trailing_slash():
    owner, repo, branch = parse_github_url("https://github.com/owner/repo/")
    assert owner == "owner"
    assert repo == "repo"
    assert branch == "main"


def test_parse_invalid_url_wrong_host():
    with pytest.raises(ValueError):
        parse_github_url("https://gitlab.com/owner/repo")


def test_parse_invalid_url_not_a_url():
    with pytest.raises(ValueError):
        parse_github_url("not-a-url")


def _make_method(
    method_name: str,
    http_method: str | None = None,
    endpoint: str | None = None,
    complexity: str = "low",
) -> MethodInfo:
    return MethodInfo(
        class_name="Foo",
        method_name=method_name,
        signature=f"void {method_name}()",
        description="desc",
        http_method=http_method,
        endpoint=endpoint,
        complexity=complexity,
    )


def _make_domain(name: str, methods: list[MethodInfo]) -> DomainAnalysis:
    return DomainAnalysis(
        name=name,
        description="desc",
        file_count=1,
        complexity="low",
        methods=methods,
        notable_aspects=[],
    )


def test_collect_endpoints_empty_domains():
    assert _collect_endpoints([]) == []


def test_collect_endpoints_no_http_methods():
    domain = _make_domain("catalog", [_make_method("doSomething")])
    assert _collect_endpoints([domain]) == []


def test_collect_endpoints_returns_http_methods_only():
    domain = _make_domain("catalog", [
        _make_method("getProduct", "GET", "/products/{id}", "low"),
        _make_method("internalHelper"),
    ])
    rows = _collect_endpoints([domain])
    assert len(rows) == 1
    assert rows[0]["Method"] == "getProduct"


def test_collect_endpoints_row_fields():
    domain = _make_domain("catalog", [
        _make_method("createProduct", "POST", "/products", "medium"),
    ])
    row = _collect_endpoints([domain])[0]
    assert row == {
        "Verb": "POST",
        "Path": "/products",
        "Method": "createProduct",
        "Domain": "catalog",
        "Description": "desc",
        "Complexity": "medium",
    }


def test_collect_endpoints_sorted_by_domain_then_path():
    d1 = _make_domain("orders", [_make_method("getOrder", "GET", "/orders/{id}")])
    d2 = _make_domain("catalog", [
        _make_method("createProduct", "POST", "/products"),
        _make_method("getProduct", "GET", "/products/{id}"),
    ])
    rows = _collect_endpoints([d1, d2])
    assert [r["Domain"] for r in rows] == ["catalog", "catalog", "orders"]
    assert rows[0]["Path"] == "/products"
    assert rows[1]["Path"] == "/products/{id}"
