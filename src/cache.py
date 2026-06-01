import hashlib
import logging
import os
from pathlib import Path

from google.cloud import storage

from src.models import DomainAnalysis

logger = logging.getLogger(__name__)


class DiskCache:
    def __init__(self, cache_dir: Path = Path(".cache")) -> None:
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _key(self, files: list[Path]) -> str:
        content = "".join(p.read_text(errors="ignore") for p in sorted(files))
        return hashlib.sha256(content.encode()).hexdigest()

    def get(self, files: list[Path]) -> DomainAnalysis | None:
        key = self._key(files)
        path = self.cache_dir / f"{key}.json"
        if path.exists():
            logger.debug("Cache hit", extra={"key": key[:8]})
            return DomainAnalysis.model_validate_json(path.read_text())
        logger.debug("Cache miss", extra={"key": key[:8]})
        return None

    def set(self, files: list[Path], analysis: DomainAnalysis) -> None:
        path = self.cache_dir / f"{self._key(files)}.json"
        path.write_text(analysis.model_dump_json(indent=2))


class GcsCache:
    def __init__(self, bucket_name: str) -> None:
        self._bucket = storage.Client().bucket(bucket_name)

    def _key(self, files: list[Path]) -> str:
        content = "".join(p.read_text(errors="ignore") for p in sorted(files))
        return hashlib.sha256(content.encode()).hexdigest()

    def get(self, files: list[Path]) -> DomainAnalysis | None:
        key = self._key(files)
        blob = self._bucket.blob(f"{key}.json")
        if not blob.exists():
            logger.debug("GCS cache miss", extra={"key": key[:8]})
            return None
        logger.debug("GCS cache hit", extra={"key": key[:8]})
        return DomainAnalysis.model_validate_json(blob.download_as_text())

    def set(self, files: list[Path], analysis: DomainAnalysis) -> None:
        key = self._key(files)
        blob = self._bucket.blob(f"{key}.json")
        blob.upload_from_string(
            analysis.model_dump_json(indent=2),
            content_type="application/json",
        )


Cache = DiskCache | GcsCache


def create_cache() -> DiskCache | GcsCache:
    bucket = os.environ.get("GCS_CACHE_BUCKET")
    if bucket:
        return GcsCache(bucket)
    return DiskCache()
