"""Supabase private Storage adapter using its HTTP API.

The implementation intentionally uses the standard library and an injectable
transport, so importing this module never requires the optional Supabase SDK.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin
from urllib.request import Request, urlopen

from .base import BlobSource, BlobStat
from .exceptions import (
    BlobConflictError,
    BlobNotFoundError,
    BlobTransportError,
)
from .keys import validate_key


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


class HttpTransport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None = None,
    ) -> HttpResponse: ...


class UrllibTransport:
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None = None,
    ) -> HttpResponse:
        request = Request(url, data=body, headers=dict(headers), method=method)
        try:
            with urlopen(request, timeout=30) as response:  # noqa: S310 - configured host
                return HttpResponse(response.status, dict(response.headers), response.read())
        except HTTPError as exc:
            return HttpResponse(exc.code, dict(exc.headers), exc.read())
        except (URLError, TimeoutError, OSError) as exc:
            raise BlobTransportError("Supabase Storage request failed") from exc


class SupabaseBlobStore:
    """Private bucket adapter authenticated with the server-only secret key."""

    def __init__(
        self,
        *,
        supabase_url: str,
        secret_key: str,
        bucket: str = "project-files",
        transport: HttpTransport | None = None,
    ) -> None:
        if not supabase_url.startswith(("https://", "http://")):
            raise ValueError("supabase_url must be an absolute HTTP(S) URL")
        if not secret_key:
            raise ValueError("secret_key is required")
        if not bucket or "/" in bucket or "\\" in bucket:
            raise ValueError("bucket must be a simple name")
        self.origin = supabase_url.rstrip("/")
        self.base_url = self.origin + "/storage/v1/"
        self.secret_key = secret_key
        self.bucket = bucket
        self.transport = transport or UrllibTransport()

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.secret_key}", "apikey": self.secret_key}

    def _object_url(self, route: str, key: str) -> str:
        encoded = quote(validate_key(key), safe="/")
        return urljoin(self.base_url, f"object/{route}{quote(self.bucket, safe='')}/{encoded}")

    @staticmethod
    def _raise_for_status(response: HttpResponse, key: str) -> None:
        if 200 <= response.status < 300:
            return
        if response.status == 404:
            raise BlobNotFoundError(f"object not found: {key}")
        if response.status == 409:
            raise BlobConflictError(f"object already exists: {key}")
        detail = ""
        try:
            payload = json.loads(response.body)
            detail = str(payload.get("message") or payload.get("error") or "")
        except (ValueError, TypeError, AttributeError):
            pass
        suffix = f": {detail}" if detail else ""
        raise BlobTransportError(f"Supabase Storage returned HTTP {response.status}{suffix}")

    @staticmethod
    def _read_source(source: BlobSource) -> bytes:
        if isinstance(source, (bytes, bytearray, memoryview)):
            return bytes(source)
        if isinstance(source, Path):
            return source.read_bytes()
        return source.read()

    def put(
        self,
        key: str,
        source: BlobSource,
        *,
        content_type: str | None = None,
        overwrite: bool = False,
    ) -> BlobStat:
        body = self._read_source(source)
        headers = self._headers
        headers["Content-Type"] = content_type or "application/octet-stream"
        headers["x-upsert"] = "true" if overwrite else "false"
        response = self.transport.request(
            "POST", self._object_url("", key), headers=headers, body=body
        )
        self._raise_for_status(response, key)
        # Upload responses do not consistently include size metadata.
        return BlobStat(key=validate_key(key), size=len(body), content_type=headers["Content-Type"])

    def download_to(self, key: str, destination: Path) -> Path:
        response = self.transport.request(
            "GET", self._object_url("authenticated/", key), headers=self._headers
        )
        self._raise_for_status(response, key)
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(dir=destination.parent, prefix=".download-", delete=False) as output:
            temporary = Path(output.name)
            output.write(response.body)
        try:
            temporary.replace(destination)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        return destination

    def stat(self, key: str) -> BlobStat:
        response = self.transport.request(
            "HEAD", self._object_url("authenticated/", key), headers=self._headers
        )
        self._raise_for_status(response, key)
        lowered = {name.lower(): value for name, value in response.headers.items()}
        try:
            size = int(lowered.get("content-length", "0"))
        except ValueError:
            size = 0
        modified: datetime | None = None
        if lowered.get("last-modified"):
            try:
                modified = parsedate_to_datetime(lowered["last-modified"])
            except (TypeError, ValueError):
                pass
        return BlobStat(
            key=validate_key(key),
            size=size,
            content_type=lowered.get("content-type"),
            etag=lowered.get("etag", "").strip('"') or None,
            last_modified=modified,
        )

    def signed_url(self, key: str, *, expires_in: int = 60) -> str:
        if expires_in < 1:
            raise ValueError("expires_in must be positive")
        headers = self._headers
        headers["Content-Type"] = "application/json"
        response = self.transport.request(
            "POST",
            self._object_url("sign/", key),
            headers=headers,
            body=json.dumps({"expiresIn": expires_in}).encode(),
        )
        self._raise_for_status(response, key)
        try:
            signed = json.loads(response.body).get("signedURL")
        except (ValueError, AttributeError) as exc:
            raise BlobTransportError("Supabase returned an invalid signed URL response") from exc
        if not isinstance(signed, str) or not signed:
            raise BlobTransportError("Supabase returned an invalid signed URL response")
        if signed.startswith("http://") or signed.startswith("https://"):
            return signed
        return urljoin(self.origin + "/", signed.lstrip("/"))

    def delete(self, key: str) -> None:
        response = self.transport.request(
            "DELETE", self._object_url("", key), headers=self._headers
        )
        if response.status == 404:
            return
        self._raise_for_status(response, key)
