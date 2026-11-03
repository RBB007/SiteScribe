"""Database configuration helpers.

Production uses PostgreSQL through psycopg 3.  Tests may provide an explicit
SQLite URL.  Configuration is deliberately read at call time so importing the
web application does not require production secrets.
"""

from __future__ import annotations

import os


class DatabaseConfigurationError(RuntimeError):
    """Raised when database configuration is absent or unsupported."""


def normalize_database_url(url: str) -> str:
    """Return a SQLAlchemy 2 URL, upgrading common provider aliases."""

    value = url.strip()
    if not value:
        raise DatabaseConfigurationError("DATABASE_URL is empty")
    if value.startswith("postgres://"):
        value = "postgresql://" + value[len("postgres://") :]
    if value.startswith("postgresql://"):
        value = "postgresql+psycopg://" + value[len("postgresql://") :]
    return value


def database_url(environ: dict[str, str] | None = None) -> str:
    source = os.environ if environ is None else environ
    try:
        return normalize_database_url(source["DATABASE_URL"])
    except KeyError as exc:
        raise DatabaseConfigurationError("DATABASE_URL is required") from exc

