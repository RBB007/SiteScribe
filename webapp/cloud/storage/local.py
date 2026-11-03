"""Filesystem implementation intended only for tests and local development."""

from __future__ import annotations

import mimetypes
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from .base import BlobSource, BlobStat
from .exceptions import BlobConflictError, BlobNotFoundError
from .keys import validate_key


class LocalBlobStore:
    def __init__(self, root: Path, *, base_url: str = "http://local.invalid/blobs") -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.base_url = base_url.rstrip("/")

    def _path(self, key: str) -> Path:
        clean_key = validate_key(key)
        target = (self.root / Path(*clean_key.split("/"))).resolve()
        if target != self.root and self.root not in target.parents:
            raise ValueError("storage key escapes the configured root")
        return target

    def put(
        self,
        key: str,
        source: BlobSource,
        *,
        content_type: str | None = None,
        overwrite: bool = False,
    ) -> BlobStat:
        target = self._path(key)
        if target.exists() and not overwrite:
            raise BlobConflictError(f"object already exists: {key}")
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(prefix=".upload-", dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as output:
                if isinstance(source, (bytes, bytearray, memoryview)):
                    output.write(source)
                elif isinstance(source, Path):
                    with source.open("rb") as input_file:
                        shutil.copyfileobj(input_file, output)
                else:
                    shutil.copyfileobj(source, output)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary_name, target)
        except BaseException:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise
        return self.stat(key, content_type=content_type)

    def download_to(self, key: str, destination: Path) -> Path:
        source = self._path(key)
        if not source.is_file():
            raise BlobNotFoundError(f"object not found: {key}")
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(prefix=".download-", dir=destination.parent)
        os.close(fd)
        try:
            shutil.copyfile(source, temporary_name)
            os.replace(temporary_name, destination)
        except BaseException:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise
        return destination

    def stat(self, key: str, *, content_type: str | None = None) -> BlobStat:
        target = self._path(key)
        if not target.is_file():
            raise BlobNotFoundError(f"object not found: {key}")
        details = target.stat()
        return BlobStat(
            key=validate_key(key),
            size=details.st_size,
            content_type=content_type or mimetypes.guess_type(target.name)[0],
            last_modified=datetime.fromtimestamp(details.st_mtime, timezone.utc),
        )

    def signed_url(self, key: str, *, expires_in: int = 60) -> str:
        if expires_in < 1:
            raise ValueError("expires_in must be positive")
        self.stat(key)
        return f"{self.base_url}/{quote(validate_key(key), safe='/')}?expires_in={expires_in}"

    def delete(self, key: str) -> None:
        target = self._path(key)
        try:
            target.unlink()
        except FileNotFoundError:
            return
        parent = target.parent
        while parent != self.root:
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent

