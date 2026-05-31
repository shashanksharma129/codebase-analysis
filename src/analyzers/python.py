from pathlib import Path

from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate

from src.analyzers.base import LanguageAnalyzer
from src.cache import DiskCache
from src.models import DomainAnalysis


class PythonAnalyzer(LanguageAnalyzer):
    @property
    def ext(self) -> str:
        return ".py"

    def get_domain_map(self, source: Path) -> dict[str, list[Path]]:
        raise NotImplementedError

    async def analyze_domain(
        self,
        domain: str,
        files: list[Path],
        llm: BaseChatModel,
        cache: DiskCache | None,
    ) -> tuple[DomainAnalysis, list[str]]:
        raise NotImplementedError

    def get_aggregation_prompt(self) -> ChatPromptTemplate:
        raise NotImplementedError
