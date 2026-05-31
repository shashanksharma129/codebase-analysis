import hashlib
from pathlib import Path

from src.models import DomainAnalysis


class DiskCache:
    def __init__(self, cache_dir: Path = Path(".cache")) -> None:
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _key(self, files: list[Path]) -> str:
        content = "".join(p.read_text(errors="ignore") for p in sorted(files))
        return hashlib.sha256(content.encode()).hexdigest()

    def get(self, files: list[Path]) -> DomainAnalysis | None:
        path = self.cache_dir / f"{self._key(files)}.json"
        if path.exists():
            return DomainAnalysis.model_validate_json(path.read_text())
        return None

    def set(self, files: list[Path], analysis: DomainAnalysis) -> None:
        path = self.cache_dir / f"{self._key(files)}.json"
        path.write_text(analysis.model_dump_json(indent=2))
