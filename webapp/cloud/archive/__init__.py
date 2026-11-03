"""Versioned, self-contained SiteScribe archive files.

This package deliberately has no Flask, database, or storage dependency.  The
cloud export service can materialize blobs as paths or streams and pass them to
``build_archive``; restores and support tools can use ``parse_archive``.
"""

from .bundle import (
    ARCHIVE_SCHEMA_VERSION,
    ArchiveAsset,
    ArchiveContents,
    ArchiveError,
    ArchiveIntegrityError,
    ArchivePathError,
    build_archive,
    parse_archive,
)

__all__ = [
    "ARCHIVE_SCHEMA_VERSION",
    "ArchiveAsset",
    "ArchiveContents",
    "ArchiveError",
    "ArchiveIntegrityError",
    "ArchivePathError",
    "build_archive",
    "parse_archive",
]
