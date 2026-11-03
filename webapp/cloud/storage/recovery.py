"""Failure compensation and storage/database reconciliation primitives."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .base import BlobStore


@dataclass(slots=True)
class CompensationResult:
    deleted: list[str] = field(default_factory=list)
    failures: dict[str, Exception] = field(default_factory=dict)


class UploadCompensation:
    """Roll back newly uploaded objects unless the unit of work commits.

    Database work remains outside this class: callers track a key immediately
    after upload, perform the database transaction, then call ``commit``.
    """

    def __init__(self, store: BlobStore) -> None:
        self.store = store
        self._keys: list[str] = []
        self._committed = False
        self.result = CompensationResult()

    def track(self, key: str) -> str:
        if self._committed:
            raise RuntimeError("cannot track an object after commit")
        self._keys.append(key)
        return key

    def commit(self) -> None:
        self._committed = True

    def rollback(self) -> CompensationResult:
        if self._committed:
            return self.result
        for key in reversed(self._keys):
            try:
                self.store.delete(key)
                self.result.deleted.append(key)
            except Exception as exc:  # cleanup must not mask the original failure
                self.result.failures[key] = exc
        self._keys.clear()
        return self.result

    def __enter__(self) -> "UploadCompensation":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        if exc_type is not None or not self._committed:
            self.rollback()
        return False


@dataclass(frozen=True, slots=True)
class ReconciliationPlan:
    missing: frozenset[str]
    orphaned: frozenset[str]
    matched: frozenset[str]

    @property
    def clean(self) -> bool:
        return not self.missing and not self.orphaned


def plan_reconciliation(
    expected_database_keys: Iterable[str], actual_storage_keys: Iterable[str]
) -> ReconciliationPlan:
    expected = frozenset(expected_database_keys)
    actual = frozenset(actual_storage_keys)
    return ReconciliationPlan(
        missing=expected - actual,
        orphaned=actual - expected,
        matched=expected & actual,
    )


def delete_orphans(store: BlobStore, plan: ReconciliationPlan) -> CompensationResult:
    """Explicitly apply only the deletion portion of a reviewed plan."""

    result = CompensationResult()
    for key in sorted(plan.orphaned):
        try:
            store.delete(key)
            result.deleted.append(key)
        except Exception as exc:
            result.failures[key] = exc
    return result

