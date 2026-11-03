"""Construction and validation of opaque, private object keys."""

from __future__ import annotations

import re
import unicodedata
from pathlib import PurePath
from uuid import UUID

from .exceptions import BlobValidationError

_UNSAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")
_REPEATED_UNDERSCORES = re.compile(r"_+")


def _canonical_uuid(value: UUID | str, field: str) -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, AttributeError, TypeError) as exc:
        raise BlobValidationError(f"{field} must be a UUID") from exc


def sanitize_filename(filename: str, *, max_length: int = 180) -> str:
    """Return a portable filename with no path or control characters."""

    if not isinstance(filename, str) or not filename.strip():
        raise BlobValidationError("filename is required")
    # Accept browser-supplied Windows paths without trusting any directory.
    basename = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    basename = unicodedata.normalize("NFKD", basename).encode("ascii", "ignore").decode()
    basename = _REPEATED_UNDERSCORES.sub("_", _UNSAFE_FILENAME.sub("_", basename))
    basename = basename.strip(" ._-")
    if not basename or basename in {".", ".."}:
        raise BlobValidationError("filename has no safe characters")

    suffix = PurePath(basename).suffix
    if len(basename) > max_length:
        stem_limit = max(1, max_length - len(suffix))
        basename = basename[:stem_limit].rstrip(" ._-") + suffix
    return basename


def build_private_key(
    *,
    workspace_id: UUID | str,
    project_id: UUID | str,
    visit_id: UUID | str,
    file_id: UUID | str,
    filename: str,
) -> str:
    """Build the frozen SiteScribe private storage key contract."""

    return "/".join(
        (
            "workspace",
            _canonical_uuid(workspace_id, "workspace_id"),
            "project",
            _canonical_uuid(project_id, "project_id"),
            "visit",
            _canonical_uuid(visit_id, "visit_id"),
            _canonical_uuid(file_id, "file_id"),
            sanitize_filename(filename),
        )
    )


def validate_key(key: str) -> str:
    """Reject absolute, ambiguous, or traversal-capable object keys."""

    if not isinstance(key, str) or not key or key.startswith(("/", "\\")):
        raise BlobValidationError("storage key must be a non-empty relative path")
    if "\\" in key or any(part in {"", ".", ".."} for part in key.split("/")):
        raise BlobValidationError("storage key contains an unsafe path segment")
    if any(ord(char) < 32 or ord(char) == 127 for char in key):
        raise BlobValidationError("storage key contains control characters")
    return key

