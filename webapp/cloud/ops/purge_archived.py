"""Physically remove resources only after their 30-day recovery window."""

from __future__ import annotations

import os
from datetime import datetime, timezone

from sqlalchemy import select

from webapp.cloud.db import create_database
from webapp.cloud.db.models import File, Project, Visit
from webapp.cloud.storage import SupabaseBlobStore


def purge_expired(database=None, store=None, *, now=None) -> tuple[int, int]:
    database = database or create_database()
    store = store or SupabaseBlobStore(
        supabase_url=os.environ["SUPABASE_URL"],
        secret_key=os.environ["SUPABASE_SECRET_KEY"],
        bucket=os.environ.get("SUPABASE_STORAGE_BUCKET", "project-files"),
    )
    now = now or datetime.now(timezone.utc)
    purged_projects = purged_visits = 0

    with database.transaction() as db:
        project_ids = list(db.scalars(select(Project.id).where(
            Project.purge_after.is_not(None), Project.purge_after <= now
        )))
        visit_ids = list(db.scalars(
            select(Visit.id)
            .join(Project, Visit.project_id == Project.id)
            .where(
                Visit.purge_after.is_not(None), Visit.purge_after <= now,
                Project.id.not_in(project_ids) if project_ids else True,
            )
        ))

    for visit_id in visit_ids:
        with database.transaction() as db:
            visit = db.get(Visit, visit_id)
            if visit is None or not _expired(visit.purge_after, now):
                continue
            keys = list(db.scalars(select(File.storage_key).where(File.visit_id == visit_id)))
            for key in keys:
                store.delete(key)
            db.delete(visit)
            purged_visits += 1

    for project_id in project_ids:
        with database.transaction() as db:
            project = db.get(Project, project_id)
            if project is None or not _expired(project.purge_after, now):
                continue
            keys = list(db.scalars(select(File.storage_key).where(File.project_id == project_id)))
            for key in keys:
                store.delete(key)
            db.delete(project)
            purged_projects += 1

    return purged_projects, purged_visits


def _expired(value, now):
    if value is None:
        return False
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return value <= now


if __name__ == "__main__":
    purge_expired()
