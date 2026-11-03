"""The provider-neutral private blob storage contract."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import BinaryIO, Protocol, TypeAlias, runtime_checkable


BlobSource: TypeAlias = bytes | bytearray | memoryview | Path | BinaryIO


@dataclass(frozen=True, slots=True)
class BlobStat:
    """Provider-neutral metadata for a private object."""

    key: str
    size: int
    content_type: str | None = None
    etag: str | None = None
    last_modified: datetime | None = None


@runtime_checkable
class BlobStore(Protocol):
    """Minimum API required by SiteScribe's file and export services."""

    def put(
        self,
        key: str,
        source: BlobSource,
        *,
        content_type: str | None = None,
        overwrite: bool = False,
    ) -> BlobStat:
        """Upload a private object and return its metadata."""

    def download_to(self, key: str, destination: Path) -> Path:
        """Download an object atomically to ``destination``."""

    def stat(self, key: str) -> BlobStat:
        """Return object metadata or raise ``BlobNotFoundError``."""

    def signed_url(self, key: str, *, expires_in: int = 60) -> str:
        """Return a short-lived read URL. Callers must never persist it."""

    def delete(self, key: str) -> None:
        """Delete an object. Missing objects are treated as already deleted."""

