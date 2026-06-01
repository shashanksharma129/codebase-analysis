from abc import ABC, abstractmethod
from pathlib import Path

from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate

from src.cache import Cache
from src.models import DomainAnalysis


class LanguageAnalyzer(ABC):

    @property
    @abstractmethod
    def ext(self) -> str:
        """File extension, e.g. '.java', '.py'"""

    @abstractmethod
    def get_domain_map(self, source: Path) -> dict[str, list[Path]]:
        """Discover domains and their source files."""

    @abstractmethod
    async def analyze_domain(
        self,
        domain: str,
        files: list[Path],
        llm: BaseChatModel,
        cache: Cache | None,
    ) -> tuple[DomainAnalysis, list[str]]:
        """Analyze one domain. Returns (analysis, skipped_file_paths)."""

    @abstractmethod
    def get_aggregation_prompt(self) -> ChatPromptTemplate:
        """Prompt template for cross-domain aggregation step."""
