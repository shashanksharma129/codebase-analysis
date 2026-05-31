from src.analyzers.base import LanguageAnalyzer


def get_analyzer(ext: str) -> LanguageAnalyzer:
    from src.analyzers.java import JavaAnalyzer
    from src.analyzers.python import PythonAnalyzer

    _REGISTRY: dict[str, type[LanguageAnalyzer]] = {
        ".java": JavaAnalyzer,
        ".py": PythonAnalyzer,
    }
    cls = _REGISTRY.get(ext)
    if cls is None:
        supported = ", ".join(_REGISTRY)
        raise ValueError(f"Unsupported extension '{ext}'. Supported: {supported}")
    return cls()
