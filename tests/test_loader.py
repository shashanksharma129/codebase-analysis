# tests/test_loader.py
from pathlib import Path

from src.loader import FileLoader


def _write(tmp_path: Path, paths: list[str]) -> None:
    for p in paths:
        full = tmp_path / p
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(f"// {p}")


def test_groups_by_services_segment(tmp_path):
    _write(tmp_path, [
        "src/main/java/com/example/services/catalog/ActorController.java",
        "src/main/java/com/example/services/catalog/ActorService.java",
        "src/main/java/com/example/services/rental/RentalController.java",
    ])
    domains = FileLoader(tmp_path).load()
    assert set(domains.keys()) == {"catalog", "rental"}
    assert len(domains["catalog"]) == 2
    assert len(domains["rental"]) == 1


def test_extension_filter_java(tmp_path):
    _write(tmp_path, ["src/Foo.java", "src/Foo.kt", "src/README.md"])
    domains = FileLoader(tmp_path, ext=".java").load()
    total = sum(len(v) for v in domains.values())
    assert total == 1


def test_extension_filter_kotlin(tmp_path):
    _write(tmp_path, ["src/Foo.java", "src/Foo.kt"])
    domains = FileLoader(tmp_path, ext=".kt").load()
    total = sum(len(v) for v in domains.values())
    assert total == 1


def test_empty_source(tmp_path):
    assert FileLoader(tmp_path).load() == {}


def test_fallback_domain_no_marker(tmp_path):
    _write(tmp_path, ["mypackage/Foo.java", "mypackage/Bar.java"])
    domains = FileLoader(tmp_path).load()
    assert "mypackage" in domains
    assert len(domains["mypackage"]) == 2


def test_fallback_domain_top_level_file(tmp_path):
    _write(tmp_path, ["Foo.java"])
    domains = FileLoader(tmp_path).load()
    assert "default" in domains


def test_modules_marker(tmp_path):
    _write(tmp_path, [
        "src/modules/auth/Login.java",
        "src/modules/auth/Logout.java",
        "src/modules/billing/Invoice.java",
    ])
    domains = FileLoader(tmp_path).load()
    assert set(domains.keys()) == {"auth", "billing"}
