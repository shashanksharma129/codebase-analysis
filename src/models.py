from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class MethodInfo(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    class_name: str = Field(serialization_alias="class")
    method_name: str
    signature: str
    description: str
    http_method: Literal["GET", "POST", "PUT", "DELETE", "PATCH"] | None = None
    endpoint: str | None = None
    complexity: Literal["low", "medium", "high"]


class DomainAnalysis(BaseModel):
    name: str
    description: str
    file_count: int
    complexity: Literal["low", "medium", "high"]
    methods: list[MethodInfo]
    notable_aspects: list[str]


class ProjectInfo(BaseModel):
    name: str
    overview: str
    purpose: str
    tech_stack: list[str]
    architecture_pattern: str


class ProjectSummary(BaseModel):
    total_files: int
    total_domains: int
    total_methods: int
    overall_complexity: Literal["low", "medium", "high"]
    key_patterns: list[str]
    notable_aspects: list[str]
    skipped_files: list[str] = Field(default_factory=list)


class ProjectReport(BaseModel):
    project: ProjectInfo
    summary: ProjectSummary


class FinalOutput(BaseModel):
    project: ProjectInfo
    domains: list[DomainAnalysis]
    summary: ProjectSummary
