from src.analyzers.base import LanguageAnalyzer


def _build_registry() -> dict[str, type[LanguageAnalyzer]]:
    from src.analyzers.java import JavaAnalyzer
    from src.analyzers.python import PythonAnalyzer
    return {
        ".java": JavaAnalyzer,
        ".py": PythonAnalyzer,
    }


_REGISTRY: dict[str, type[LanguageAnalyzer]] | None = None


def get_analyzer(ext: str) -> LanguageAnalyzer:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = _build_registry()
    cls = _REGISTRY.get(ext)
    if cls is None:
        supported = ", ".join(_REGISTRY)
        raise ValueError(f"Unsupported extension '{ext}'. Supported: {supported}")
    return cls()
