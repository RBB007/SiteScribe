"""Workspace-scoped repositories and archive lifecycle operations."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from .models import (
    AuthSession,
    MemberRole,
    MemberStatus,
    Profile,
    Project,
    Visit,
    Workspace,
    WorkspaceMember,
    utc_now,
)

RECOVERY_WINDOW = timedelta(days=30)


class ResourceNotFound(LookupError):
    """A resource is absent or intentionally hidden from this workspace."""


class MembershipRequired(PermissionError):
    """The actor is not an active member of the workspace."""


class AdminRequired(PermissionError):
    """The operation requires the administrator role."""


class ArchivedResource(RuntimeError):
    """The requested mutation is not permitted while archived."""


def hash_session_id(opaque_session_id: str) -> str:
    if not opaque_session_id:
        raise ValueError("session ID is required")
    return hashlib.sha256(opaque_session_id.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class IssuedAuthSession:
    """The raw cookie value is returned only at issue time."""

    opaque_session_id: str
    record: AuthSession


class AuthSessionRepository:
    """Store encrypted provider tokens behind a hashed opaque cookie ID.

    Token encryption is owned by the auth service (Fernet/MultiFernet); this
    repository accepts ciphertext only and exposes no plaintext-token fields.
    """

    def __init__(self, session: Session):
        self.session = session

    def issue(
        self,
        *,
        profile_id: uuid.UUID,
        access_token_ciphertext: str,
        refresh_token_ciphertext: str,
        access_token_expires_at: datetime,
        session_expires_at: datetime,
    ) -> IssuedAuthSession:
        if session_expires_at <= access_token_expires_at:
            raise ValueError("session expiry must be later than access token expiry")
        opaque_session_id = secrets.token_urlsafe(32)
        record = AuthSession(
            profile_id=profile_id,
            session_id_hash=hash_session_id(opaque_session_id),
            access_token_ciphertext=_required_text(
                access_token_ciphertext, "encrypted access token"
            ),
            refresh_token_ciphertext=_required_text(
                refresh_token_ciphertext, "encrypted refresh token"
            ),
            access_token_expires_at=access_token_expires_at,
            session_expires_at=session_expires_at,
        )
        self.session.add(record)
        self.session.flush()
        return IssuedAuthSession(opaque_session_id=opaque_session_id, record=record)

    def resolve(self, opaque_session_id: str, *, now: datetime | None = None) -> AuthSession | None:
        current_time = now or utc_now()
        record = self.session.scalar(
            select(AuthSession).where(
                AuthSession.session_id_hash == hash_session_id(opaque_session_id),
                AuthSession.revoked_at.is_(None),
                AuthSession.session_expires_at > current_time,
            )
        )
        if record is not None:
            record.last_seen_at = current_time
        return record

    def rotate_tokens(
        self,
        record: AuthSession,
        *,
        access_token_ciphertext: str,
        refresh_token_ciphertext: str,
        access_token_expires_at: datetime,
    ) -> None:
        if record.revoked_at is not None:
            raise ValueError("cannot rotate a revoked session")
        record.access_token_ciphertext = _required_text(
            access_token_ciphertext, "encrypted access token"
        )
        record.refresh_token_ciphertext = _required_text(
            refresh_token_ciphertext, "encrypted refresh token"
        )
        record.access_token_expires_at = access_token_expires_at
        self.session.flush()

    def revoke(self, opaque_session_id: str, *, now: datetime | None = None) -> bool:
        record = self.session.scalar(
            select(AuthSession).where(
                AuthSession.session_id_hash == hash_session_id(opaque_session_id),
                AuthSession.revoked_at.is_(None),
            )
        )
        if record is None:
            return False
        record.revoked_at = now or utc_now()
        self.session.flush()
        return True


def require_active_member(
    session: Session, workspace_id: uuid.UUID, profile_id: uuid.UUID
) -> WorkspaceMember:
    member = session.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.profile_id == profile_id,
            WorkspaceMember.status == MemberStatus.ACTIVE,
        )
    )
    if member is None:
        raise MembershipRequired("active workspace membership is required")
    return member


def require_admin(session: Session, workspace_id: uuid.UUID, profile_id: uuid.UUID) -> WorkspaceMember:
    member = require_active_member(session, workspace_id, profile_id)
    if member.role != MemberRole.ADMIN:
        raise AdminRequired("workspace administrator role is required")
    return member


class WorkspaceRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, name: str) -> Workspace:
        workspace = Workspace(name=_required_text(name, "workspace name"))
        self.session.add(workspace)
        self.session.flush()
        return workspace

    def add_member(
        self,
        workspace_id: uuid.UUID,
        profile: Profile,
        *,
        role: MemberRole = MemberRole.MEMBER,
        status: MemberStatus = MemberStatus.PENDING,
    ) -> WorkspaceMember:
        member = WorkspaceMember(
            workspace_id=workspace_id, profile=profile, role=role, status=status
        )
        self.session.add(member)
        self.session.flush()
        return member


class ProjectRepository:
    def __init__(self, session: Session, workspace_id: uuid.UUID, actor_id: uuid.UUID):
        self.session = session
        self.workspace_id = workspace_id
        self.actor_id = actor_id

    def _authorize(self) -> WorkspaceMember:
        return require_active_member(self.session, self.workspace_id, self.actor_id)

    def _base(self) -> Select[tuple[Project]]:
        return select(Project).where(Project.workspace_id == self.workspace_id)

    def list(self, *, archived: bool = False) -> list[Project]:
        self._authorize()
        archive_filter = Project.archived_at.is_not(None) if archived else Project.archived_at.is_(None)
        return list(
            self.session.scalars(
                self._base().where(archive_filter).order_by(func.lower(Project.name), Project.id)
            )
        )

    def get(self, project_id: uuid.UUID, *, include_archived: bool = False) -> Project:
        self._authorize()
        query = self._base().where(Project.id == project_id)
        if not include_archived:
            query = query.where(Project.archived_at.is_(None))
        project = self.session.scalar(query)
        if project is None:
            raise ResourceNotFound("project not found")
        return project

    def create(
        self,
        name: str,
        *,
        project_number: str | None = None,
        address: str | None = None,
        client: str | None = None,
    ) -> Project:
        self._authorize()
        project = Project(
            workspace_id=self.workspace_id,
            name=_required_text(name, "project name"),
            project_number=_optional_text(project_number),
            address=_optional_text(address),
            client=_optional_text(client),
        )
        self.session.add(project)
        self.session.flush()
        return project

    def archive(self, project_id: uuid.UUID, *, now: datetime | None = None) -> Project:
        project = self.get(project_id)
        archived_at = now or utc_now()
        project.archived_at = archived_at
        project.purge_after = archived_at + RECOVERY_WINDOW
        for visit in project.visits:
            if visit.archived_at is None:
                visit.archived_at = archived_at
                visit.purge_after = project.purge_after
        self.session.flush()
        return project

    def restore(self, project_id: uuid.UUID) -> Project:
        project = self.get(project_id, include_archived=True)
        if project.archived_at is None:
            return project
        cascade_time = project.archived_at
        project.archived_at = None
        project.purge_after = None
        # Only restore visits archived by this project cascade; visits archived
        # separately before the project retain their own recovery lifecycle.
        for visit in project.visits:
            if visit.archived_at == cascade_time:
                visit.archived_at = None
                visit.purge_after = None
        self.session.flush()
        return project


class VisitRepository:
    def __init__(self, session: Session, workspace_id: uuid.UUID, actor_id: uuid.UUID):
        self.session = session
        self.workspace_id = workspace_id
        self.actor_id = actor_id

    def _authorize(self) -> None:
        require_active_member(self.session, self.workspace_id, self.actor_id)

    def _project(self, project_id: uuid.UUID, *, include_archived: bool = False) -> Project:
        return ProjectRepository(self.session, self.workspace_id, self.actor_id).get(
            project_id, include_archived=include_archived
        )

    def list(self, project_id: uuid.UUID, *, archived: bool = False) -> list[Visit]:
        self._project(project_id, include_archived=archived)
        archive_filter = Visit.archived_at.is_not(None) if archived else Visit.archived_at.is_(None)
        return list(
            self.session.scalars(
                select(Visit)
                .where(Visit.project_id == project_id, archive_filter)
                .order_by(Visit.visit_date.desc(), Visit.created_at.desc(), Visit.id)
            )
        )

    def get(
        self, project_id: uuid.UUID, visit_id: uuid.UUID, *, include_archived: bool = False
    ) -> Visit:
        self._project(project_id, include_archived=include_archived)
        query = select(Visit).where(Visit.id == visit_id, Visit.project_id == project_id)
        if not include_archived:
            query = query.where(Visit.archived_at.is_(None))
        visit = self.session.scalar(query)
        if visit is None:
            raise ResourceNotFound("visit not found")
        return visit

    def create(self, project_id: uuid.UUID, visit_date: date, **values: object) -> Visit:
        project = self._project(project_id)
        if project.archived_at is not None:
            raise ArchivedResource("cannot create a visit in an archived project")
        allowed = {
            "report_number",
            "engineer",
            "visit_time",
            "conditions",
            "attendees",
            "summary",
            "report_options",
        }
        supplied = {key: value for key, value in values.items() if key in allowed}
        visit = Visit(project_id=project_id, visit_date=visit_date, **supplied)
        self.session.add(visit)
        self.session.flush()
        return visit

    def archive(
        self, project_id: uuid.UUID, visit_id: uuid.UUID, *, now: datetime | None = None
    ) -> Visit:
        visit = self.get(project_id, visit_id)
        archived_at = now or utc_now()
        visit.archived_at = archived_at
        visit.purge_after = archived_at + RECOVERY_WINDOW
        self.session.flush()
        return visit

    def restore(self, project_id: uuid.UUID, visit_id: uuid.UUID) -> Visit:
        project = self._project(project_id, include_archived=True)
        if project.archived_at is not None:
            raise ArchivedResource("restore the project before restoring its visit")
        visit = self.get(project_id, visit_id, include_archived=True)
        visit.archived_at = None
        visit.purge_after = None
        self.session.flush()
        return visit


def _required_text(value: str, label: str) -> str:
    result = value.strip()
    if not result:
        raise ValueError(f"{label} is required")
    return result


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    result = value.strip()
    return result or None
