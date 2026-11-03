from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import event, inspect, select
from sqlalchemy.exc import IntegrityError

from webapp.cloud.db.config import DatabaseConfigurationError, database_url, normalize_database_url
from webapp.cloud.db.models import (
    Base,
    MemberRole,
    MemberStatus,
    Profile,
    Project,
    Visit,
)
from webapp.cloud.db.repositories import (
    AuthSessionRepository,
    ArchivedResource,
    MembershipRequired,
    ProjectRepository,
    ResourceNotFound,
    VisitRepository,
    WorkspaceRepository,
    hash_session_id,
)
from webapp.cloud.db.session import create_database


@pytest.fixture
def db():
    database = create_database("sqlite+pysqlite:///:memory:")

    @event.listens_for(database.engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(database.engine)
    try:
        yield database
    finally:
        Base.metadata.drop_all(database.engine)
        database.engine.dispose()


def seed(session, *, active=True, role=MemberRole.MEMBER):
    profile = Profile(id=uuid.uuid4(), email=f"{uuid.uuid4()}@example.com")
    workspace = WorkspaceRepository(session).create("MKA")
    WorkspaceRepository(session).add_member(
        workspace.id,
        profile,
        role=role,
        status=MemberStatus.ACTIVE if active else MemberStatus.PENDING,
    )
    session.flush()
    return workspace, profile


def test_database_url_normalizes_provider_aliases():
    assert normalize_database_url("postgres://host/db") == "postgresql+psycopg://host/db"
    assert normalize_database_url("postgresql://host/db") == "postgresql+psycopg://host/db"
    assert normalize_database_url("sqlite:///test.db") == "sqlite:///test.db"
    with pytest.raises(DatabaseConfigurationError):
        database_url({})


def test_schema_create_and_drop_has_all_locked_tables(db):
    expected = {
        "profiles",
        "auth_sessions",
        "workspaces",
        "workspace_members",
        "projects",
        "visits",
        "items",
        "observations",
        "files",
        "observation_files",
        "plans",
        "exports",
        "audit_events",
        "backup_runs",
    }
    assert expected == set(inspect(db.engine).get_table_names())
    Base.metadata.drop_all(db.engine)
    assert inspect(db.engine).get_table_names() == []
    Base.metadata.create_all(db.engine)


def test_transaction_commits_and_rolls_back(db):
    first_id = uuid.uuid4()
    with db.transaction() as session:
        session.add(Profile(id=first_id, email="ok@example.com"))
    with pytest.raises(RuntimeError), db.transaction() as session:
        session.add(Profile(id=uuid.uuid4(), email="rolled-back@example.com"))
        raise RuntimeError("stop")
    with db.transaction() as session:
        assert session.get(Profile, first_id) is not None
        assert session.scalar(select(Profile).where(Profile.email == "rolled-back@example.com")) is None


def test_inactive_and_cross_workspace_members_cannot_query_projects(db):
    with db.transaction() as session:
        workspace, pending = seed(session, active=False)
        with pytest.raises(MembershipRequired):
            ProjectRepository(session, workspace.id, pending.id).list()

        other = Profile(id=uuid.uuid4(), email="other@example.com")
        session.add(other)
        with pytest.raises(MembershipRequired):
            ProjectRepository(session, workspace.id, other.id).list()


def test_projects_are_case_insensitively_sorted_and_scoped(db):
    with db.transaction() as session:
        workspace, actor = seed(session)
        repo = ProjectRepository(session, workspace.id, actor.id)
        repo.create("zulu")
        repo.create("Alpha")
        repo.create("bravo")
        assert [project.name for project in repo.list()] == ["Alpha", "bravo", "zulu"]

        other_workspace, other_actor = seed(session)
        ProjectRepository(session, other_workspace.id, other_actor.id).create("Hidden")
        assert [project.name for project in repo.list()] == ["Alpha", "bravo", "zulu"]
        with pytest.raises(ResourceNotFound):
            repo.get(ProjectRepository(session, other_workspace.id, other_actor.id).list()[0].id)


def test_visits_sort_newest_then_creation_and_validate_unique_item_numbers(db):
    with db.transaction() as session:
        workspace, actor = seed(session)
        project = ProjectRepository(session, workspace.id, actor.id).create("Tower")
        visits = VisitRepository(session, workspace.id, actor.id)
        older = visits.create(project.id, date(2026, 1, 1))
        first = visits.create(project.id, date(2026, 2, 1))
        second = visits.create(project.id, date(2026, 2, 1))
        older.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        first.created_at = datetime(2026, 2, 1, tzinfo=timezone.utc)
        second.created_at = datetime(2026, 2, 2, tzinfo=timezone.utc)
        session.flush()
        assert [v.id for v in visits.list(project.id)] == [second.id, first.id, older.id]


def test_archive_restore_uses_exact_thirty_day_window_and_cascades(db):
    now = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)
    with db.transaction() as session:
        workspace, actor = seed(session)
        projects = ProjectRepository(session, workspace.id, actor.id)
        project = projects.create("Tower")
        visits = VisitRepository(session, workspace.id, actor.id)
        visit = visits.create(project.id, date(2026, 11, 1))

        projects.archive(project.id, now=now)
        assert project.purge_after == now + timedelta(days=30)
        assert visit.archived_at == now
        assert projects.list() == []
        assert projects.list(archived=True) == [project]
        with pytest.raises(ResourceNotFound):
            visits.get(project.id, visit.id)

        projects.restore(project.id)
        assert project.archived_at is None and project.purge_after is None
        assert visit.archived_at is None and visit.purge_after is None


def test_restoring_project_preserves_visit_archived_before_project(db):
    with db.transaction() as session:
        workspace, actor = seed(session)
        projects = ProjectRepository(session, workspace.id, actor.id)
        project = projects.create("Tower")
        visits = VisitRepository(session, workspace.id, actor.id)
        visit = visits.create(project.id, date(2026, 11, 1))
        visits.archive(project.id, visit.id, now=datetime(2026, 10, 1, tzinfo=timezone.utc))
        projects.archive(project.id, now=datetime(2026, 11, 1, tzinfo=timezone.utc))
        projects.restore(project.id)
        assert visit.archived_at is not None


def test_visit_cannot_restore_until_project_is_restored(db):
    with db.transaction() as session:
        workspace, actor = seed(session)
        projects = ProjectRepository(session, workspace.id, actor.id)
        project = projects.create("Tower")
        visits = VisitRepository(session, workspace.id, actor.id)
        visit = visits.create(project.id, date(2026, 11, 1))
        projects.archive(project.id)
        with pytest.raises(ArchivedResource):
            visits.restore(project.id, visit.id)


def test_membership_and_archive_constraints_are_enforced(db):
    with pytest.raises(IntegrityError), db.transaction() as session:
        workspace, actor = seed(session)
        WorkspaceRepository(session).add_member(
            workspace.id, actor, role=MemberRole.ADMIN, status=MemberStatus.ACTIVE
        )
    with pytest.raises(IntegrityError), db.transaction() as session:
        workspace, actor = seed(session)
        session.add(Project(workspace_id=workspace.id, name="Bad", archived_at=datetime.now(timezone.utc)))


def test_auth_session_issues_raw_id_once_and_persists_only_its_hash(db):
    now = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)
    with db.transaction() as session:
        profile = Profile(id=uuid.uuid4(), email="auth@example.com")
        session.add(profile)
        session.flush()
        repository = AuthSessionRepository(session)
        issued = repository.issue(
            profile_id=profile.id,
            access_token_ciphertext="fernet-access-ciphertext",
            refresh_token_ciphertext="fernet-refresh-ciphertext",
            access_token_expires_at=now + timedelta(hours=1),
            session_expires_at=now + timedelta(days=7),
        )
        assert issued.record.session_id_hash == hash_session_id(issued.opaque_session_id)
        assert issued.opaque_session_id not in issued.record.session_id_hash
        assert repository.resolve("wrong-cookie", now=now) is None
        assert repository.resolve(issued.opaque_session_id, now=now) == issued.record
        assert repository.revoke(issued.opaque_session_id, now=now)
        assert repository.resolve(issued.opaque_session_id, now=now) is None
