from pathlib import Path

_DOMAIN_MARKERS = frozenset(
    {"services", "modules", "features", "domain", "domains", "packages"}
)
_SKIP_SEGMENTS = frozenset({
    "src", "main", "test", "java", "kotlin", "resources",
    "com", "org", "net", "io", "app", "application",
})


class FileLoader:
    def __init__(self, source: Path, ext: str = ".java") -> None:
        self.source = source
        self.ext = ext

    def load(self) -> dict[str, list[Path]]:
        domains: dict[str, list[Path]] = {}
        for path in sorted(self.source.rglob(f"*{self.ext}")):
            domain = self._domain_for(path)
            domains.setdefault(domain, []).append(path)
        return domains

    def _domain_for(self, path: Path) -> str:
        parts = path.relative_to(self.source).parts[:-1]  # exclude filename
        for i, part in enumerate(parts):
            if part in _DOMAIN_MARKERS and i + 1 < len(parts):
                return parts[i + 1]
        for part in parts:
            if part.lower() not in _SKIP_SEGMENTS:
                return part
        return "default"
