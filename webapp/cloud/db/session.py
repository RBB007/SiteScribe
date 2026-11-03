"""SQLAlchemy engine and transaction lifecycle."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from .config import database_url, normalize_database_url


@dataclass(frozen=True)
class Database:
    """Own the engine and short-lived session factory for one database."""

    engine: Engine
    sessions: sessionmaker[Session]

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        """Commit a unit of work or roll it back on any exception."""

        session = self.sessions()
        try:
            with session.begin():
                yield session
        finally:
            session.close()


def create_database(
    url: str | None = None,
    *,
    echo: bool = False,
    **engine_options: object,
) -> Database:
    resolved = normalize_database_url(url) if url is not None else database_url()
    options: dict[str, object] = {"pool_pre_ping": True, "echo": echo}
    options.update(engine_options)
    engine = create_engine(resolved, **options)
    factory = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
    return Database(engine=engine, sessions=factory)

