import pytest
from src.analyzers import get_analyzer, LanguageAnalyzer


def test_get_analyzer_java():
    from src.analyzers.java import JavaAnalyzer
    analyzer = get_analyzer(".java")
    assert isinstance(analyzer, JavaAnalyzer)
    assert analyzer.ext == ".java"


def test_get_analyzer_python():
    from src.analyzers.python import PythonAnalyzer
    analyzer = get_analyzer(".py")
    assert isinstance(analyzer, PythonAnalyzer)
    assert analyzer.ext == ".py"


def test_get_analyzer_unsupported():
    with pytest.raises(ValueError, match="Unsupported extension"):
        get_analyzer(".go")


def test_analyzer_is_abstract():
    with pytest.raises(TypeError):
        LanguageAnalyzer()
