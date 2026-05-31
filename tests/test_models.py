import pytest
from pydantic import ValidationError

from src.models import (
    DomainAnalysis,
    FinalOutput,
    MethodInfo,
    ProjectInfo,
    ProjectReport,
    ProjectSummary,
)


def _method(**overrides) -> dict:
    return {
        "class_name": "ActorController",
        "method_name": "getActor",
        "signature": "ResponseEntity<ActorDto> getActor(Integer id)",
        "description": "Fetches actor by ID",
        "http_method": "GET",
        "endpoint": "/api/v1/actors/{id}",
        "complexity": "low",
        **overrides,
    }


def test_method_info_valid():
    m = MethodInfo(**_method())
    assert m.class_name == "ActorController"
    assert m.http_method == "GET"
    assert m.endpoint == "/api/v1/actors/{id}"


def test_method_info_nullable_fields():
    m = MethodInfo(**_method(http_method=None, endpoint=None))
    assert m.http_method is None
    assert m.endpoint is None


def test_method_info_invalid_complexity():
    with pytest.raises(ValidationError):
        MethodInfo(**_method(complexity="extreme"))


def test_method_info_invalid_http_method():
    with pytest.raises(ValidationError):
        MethodInfo(**_method(http_method="OPTIONS"))


def test_method_info_serializes_class_alias():
    m = MethodInfo(**_method())
    data = m.model_dump(by_alias=True)
    assert "class" in data
    assert "class_name" not in data


def _domain(**overrides) -> dict:
    return {
        "name": "catalog",
        "description": "Film catalog domain",
        "file_count": 10,
        "complexity": "medium",
        "methods": [],
        "notable_aspects": ["MapStruct"],
        **overrides,
    }


def test_domain_analysis_valid():
    d = DomainAnalysis(**_domain())
    assert d.name == "catalog"
    assert d.file_count == 10


def test_domain_analysis_round_trip():
    d = DomainAnalysis(**_domain())
    assert DomainAnalysis.model_validate_json(d.model_dump_json()) == d


def test_domain_analysis_invalid_complexity():
    with pytest.raises(ValidationError):
        DomainAnalysis(**_domain(complexity="extreme"))


def test_project_summary_skipped_files_defaults_empty():
    s = ProjectSummary(
        total_files=1,
        total_domains=1,
        total_methods=0,
        overall_complexity="low",
        key_patterns=[],
        notable_aspects=[],
    )
    assert s.skipped_files == []


def test_final_output_structure():
    info = ProjectInfo(
        name="test", overview="o", purpose="p", tech_stack=[], architecture_pattern="MVC"
    )
    summary = ProjectSummary(
        total_files=1,
        total_domains=1,
        total_methods=0,
        overall_complexity="low",
        key_patterns=[],
        notable_aspects=[],
    )
    out = FinalOutput(project=info, domains=[DomainAnalysis(**_domain())], summary=summary)
    assert len(out.domains) == 1


def test_project_report_valid():
    info = ProjectInfo(
        name="test", overview="o", purpose="p", tech_stack=[], architecture_pattern="MVC"
    )
    summary = ProjectSummary(
        total_files=1,
        total_domains=1,
        total_methods=0,
        overall_complexity="low",
        key_patterns=[],
        notable_aspects=[],
    )
    report = ProjectReport(project=info, summary=summary)
    assert report.project.name == "test"
    assert report.summary.total_files == 1
