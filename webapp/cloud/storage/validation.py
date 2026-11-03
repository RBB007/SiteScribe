"""Configurable upload validation independent of Flask and providers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePath

from .exceptions import BlobValidationError
from .keys import sanitize_filename

DEFAULT_ALLOWED_CONTENT_TYPES = frozenset(
    {
        "application/json",
        "application/msword",
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/zip",
        "audio/aac",
        "audio/m4a",
        "audio/mp4",
        "audio/mpeg",
        "audio/ogg",
        "audio/wav",
        "audio/webm",
        "image/heic",
        "image/heif",
        "image/jpeg",
        "image/png",
        "image/webp",
        "text/plain",
    }
)


@dataclass(frozen=True, slots=True)
class UploadPolicy:
    max_bytes: int = 100 * 1024 * 1024
    allowed_content_types: frozenset[str] = DEFAULT_ALLOWED_CONTENT_TYPES
    allowed_extensions: frozenset[str] | None = None
    allow_empty: bool = False


@dataclass(frozen=True, slots=True)
class ValidatedUpload:
    filename: str
    content_type: str
    size: int


def validate_upload(
    *,
    filename: str,
    content_type: str,
    size: int,
    policy: UploadPolicy = UploadPolicy(),
) -> ValidatedUpload:
    """Validate upload metadata before reading or storing its body."""

    safe_name = sanitize_filename(filename)
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        raise BlobValidationError("upload size must be a non-negative integer")
    if size == 0 and not policy.allow_empty:
        raise BlobValidationError("empty uploads are not allowed")
    if size > policy.max_bytes:
        raise BlobValidationError(f"upload exceeds the {policy.max_bytes}-byte limit")
    normalized_type = content_type.partition(";")[0].strip().lower()
    if not normalized_type or normalized_type not in policy.allowed_content_types:
        raise BlobValidationError(f"content type is not allowed: {normalized_type or 'missing'}")
    suffix = PurePath(safe_name).suffix.lower()
    if policy.allowed_extensions is not None and suffix not in {
        extension.lower() if extension.startswith(".") else f".{extension.lower()}"
        for extension in policy.allowed_extensions
    }:
        raise BlobValidationError(f"file extension is not allowed: {suffix or 'missing'}")
    return ValidatedUpload(safe_name, normalized_type, size)

