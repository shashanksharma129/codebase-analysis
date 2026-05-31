# tests/test_cache.py

from src.cache import DiskCache
from src.models import DomainAnalysis


def _domain(name: str = "catalog") -> DomainAnalysis:
    return DomainAnalysis(
        name=name,
        description="test",
        file_count=1,
        complexity="low",
        methods=[],
        notable_aspects=[],
    )


def test_cache_miss_returns_none(tmp_path):
    cache = DiskCache(tmp_path / ".cache")
    f = tmp_path / "Foo.java"
    f.write_text("class Foo {}")
    assert cache.get([f]) is None


def test_set_then_get_returns_domain(tmp_path):
    cache = DiskCache(tmp_path / ".cache")
    f = tmp_path / "Foo.java"
    f.write_text("class Foo {}")
    domain = _domain()
    cache.set([f], domain)
    assert cache.get([f]) == domain


def test_cache_invalidated_on_content_change(tmp_path):
    cache = DiskCache(tmp_path / ".cache")
    f = tmp_path / "Foo.java"
    f.write_text("class Foo {}")
    cache.set([f], _domain())
    f.write_text("class Foo { void bar() {} }")
    assert cache.get([f]) is None


def test_cache_key_order_independent(tmp_path):
    cache = DiskCache(tmp_path / ".cache")
    f1, f2 = tmp_path / "A.java", tmp_path / "B.java"
    f1.write_text("class A {}")
    f2.write_text("class B {}")
    cache.set([f1, f2], _domain("order-test"))
    assert cache.get([f2, f1]) == _domain("order-test")


def test_cache_creates_directory(tmp_path):
    cache_dir = tmp_path / "nested" / ".cache"
    cache = DiskCache(cache_dir)
    f = tmp_path / "X.java"
    f.write_text("x")
    cache.set([f], _domain())
    assert cache_dir.exists()


def test_multiple_domains_independent(tmp_path):
    cache = DiskCache(tmp_path / ".cache")
    f1, f2 = tmp_path / "A.java", tmp_path / "B.java"
    f1.write_text("class A {}")
    f2.write_text("class B {}")
    cache.set([f1], _domain("alpha"))
    cache.set([f2], _domain("beta"))
    assert cache.get([f1]) == _domain("alpha")
    assert cache.get([f2]) == _domain("beta")
