"""Relational schema for the SiteScribe cloud application.

UUIDs use SQLAlchemy's portable ``Uuid`` type: PostgreSQL receives native UUID
columns and SQLite tests receive canonical 32-character values. Enum columns
use CHECK constraints rather than PostgreSQL enum types so migrations remain
transactional and portable.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class MemberRole(str, enum.Enum):
    ADMIN = "admin"
    MEMBER = "member"


class MemberStatus(str, enum.Enum):
    PENDING = "pending"
    ACTIVE = "active"
    DISABLED = "disabled"


class ExportStatus(str, enum.Enum):
    PENDING = "pending"
    BUILDING = "building"
    COMPLETE = "complete"
    FAILED = "failed"


class BackupStatus(str, enum.Enum):
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


def enum_column(enum_type: type[enum.Enum], name: str) -> Enum:
    return Enum(
        enum_type,
        name=name,
        native_enum=False,
        create_constraint=True,
        values_callable=lambda values: [value.value for value in values],
    )


class IdMixin:
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class ArchiveMixin:
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    purge_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class Profile(Base, TimestampMixin):
    __tablename__ = "profiles"

    # This is the UUID issued by Supabase Auth; application code supplies it.
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    display_name: Mapped[str | None] = mapped_column(String(200))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    memberships: Mapped[list[WorkspaceMember]] = relationship(back_populates="profile")
    auth_sessions: Mapped[list[AuthSession]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )


class AuthSession(Base, IdMixin):
    """Encrypted provider credentials behind a hashed opaque cookie ID."""

    __tablename__ = "auth_sessions"
    __table_args__ = (
        UniqueConstraint("session_id_hash", name="uq_auth_sessions_id_hash"),
        Index("ix_auth_sessions_profile_expiry", "profile_id", "session_expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_id_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    access_token_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    access_token_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    session_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    profile: Mapped[Profile] = relationship(back_populates="auth_sessions")


class Workspace(Base, IdMixin, TimestampMixin):
    __tablename__ = "workspaces"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    members: Mapped[list[WorkspaceMember]] = relationship(back_populates="workspace")
    projects: Mapped[list[Project]] = relationship(back_populates="workspace")


class WorkspaceMember(Base, IdMixin, TimestampMixin):
    __tablename__ = "workspace_members"
    __table_args__ = (
        UniqueConstraint("workspace_id", "profile_id", name="uq_workspace_member_profile"),
        Index("ix_workspace_members_profile_status", "profile_id", "status"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[MemberRole] = mapped_column(
        enum_column(MemberRole, "member_role"), default=MemberRole.MEMBER, nullable=False
    )
    status: Mapped[MemberStatus] = mapped_column(
        enum_column(MemberStatus, "member_status"), default=MemberStatus.PENDING, nullable=False
    )

    workspace: Mapped[Workspace] = relationship(back_populates="members")
    profile: Mapped[Profile] = relationship(back_populates="memberships")


class Project(Base, IdMixin, TimestampMixin, ArchiveMixin):
    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint(
            "(archived_at IS NULL AND purge_after IS NULL) OR "
            "(archived_at IS NOT NULL AND purge_after IS NOT NULL)",
            name="ck_projects_archive_pair",
        ),
        Index("ix_projects_workspace_name_id", "workspace_id", text("lower(name)"), "id"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    project_number: Mapped[str | None] = mapped_column(String(100))
    address: Mapped[str | None] = mapped_column(Text)
    client: Mapped[str | None] = mapped_column(String(300))

    workspace: Mapped[Workspace] = relationship(back_populates="projects")
    visits: Mapped[list[Visit]] = relationship(back_populates="project", cascade="all, delete-orphan")


class Visit(Base, IdMixin, TimestampMixin, ArchiveMixin):
    __tablename__ = "visits"
    __table_args__ = (
        CheckConstraint(
            "(archived_at IS NULL AND purge_after IS NULL) OR "
            "(archived_at IS NOT NULL AND purge_after IS NOT NULL)",
            name="ck_visits_archive_pair",
        ),
        Index("ix_visits_project_order", "project_id", "visit_date", "created_at", "id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    visit_date: Mapped[date] = mapped_column(Date, nullable=False)
    report_number: Mapped[str | None] = mapped_column(String(100))
    engineer: Mapped[str | None] = mapped_column(String(200))
    visit_time: Mapped[str | None] = mapped_column(String(100))
    conditions: Mapped[str | None] = mapped_column(Text)
    attendees: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    report_options: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    project: Mapped[Project] = relationship(back_populates="visits")
    items: Mapped[list[Item]] = relationship(back_populates="visit", cascade="all, delete-orphan")
    files: Mapped[list[File]] = relationship(back_populates="visit")


class Item(Base, IdMixin, TimestampMixin):
    __tablename__ = "items"
    __table_args__ = (
        UniqueConstraint("visit_id", "number", name="uq_items_visit_number"),
        Index("ix_items_visit_position", "visit_id", "position", "id"),
    )

    visit_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("visits.id", ondelete="CASCADE"), nullable=False, index=True
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    visit: Mapped[Visit] = relationship(back_populates="items")
    observations: Mapped[list[Observation]] = relationship(
        back_populates="item", cascade="all, delete-orphan"
    )


class Observation(Base, IdMixin, TimestampMixin):
    __tablename__ = "observations"
    __table_args__ = (
        UniqueConstraint("item_id", "sequence", name="uq_observations_item_sequence"),
        Index("ix_observations_item_sequence", "item_id", "sequence"),
    )

    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    caption: Mapped[str | None] = mapped_column(Text)
    severity: Mapped[str | None] = mapped_column(String(50))
    tags: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    action: Mapped[str | None] = mapped_column(Text)
    include_in_report: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    plan_page: Mapped[int | None] = mapped_column(Integer)
    plan_x: Mapped[float | None]
    plan_y: Mapped[float | None]

    item: Mapped[Item] = relationship(back_populates="observations")
    file_links: Mapped[list[ObservationFile]] = relationship(
        back_populates="observation", cascade="all, delete-orphan"
    )


class File(Base, IdMixin, TimestampMixin):
    __tablename__ = "files"
    __table_args__ = (
        UniqueConstraint("storage_key", name="uq_files_storage_key"),
        CheckConstraint("size_bytes >= 0", name="ck_files_nonnegative_size"),
        Index("ix_files_workspace_project_visit", "workspace_id", "project_id", "visit_id"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    visit_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("visits.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("profiles.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    visit: Mapped[Visit | None] = relationship(back_populates="files")
    observation_links: Mapped[list[ObservationFile]] = relationship(
        back_populates="file", cascade="all, delete-orphan"
    )


class ObservationFile(Base):
    __tablename__ = "observation_files"
    __table_args__ = (UniqueConstraint("observation_id", "position", name="uq_observation_files_position"),)

    observation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("observations.id", ondelete="CASCADE"), primary_key=True
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE"), primary_key=True
    )
    media_role: Mapped[str] = mapped_column(String(50), nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    observation: Mapped[Observation] = relationship(back_populates="file_links")
    file: Mapped[File] = relationship(back_populates="observation_links")


class Plan(Base, IdMixin, TimestampMixin):
    __tablename__ = "plans"

    visit_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("visits.id", ondelete="CASCADE"), nullable=False, index=True
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    page_count: Mapped[int] = mapped_column(Integer, nullable=False)
    plan_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class Export(Base, IdMixin, TimestampMixin):
    __tablename__ = "exports"
    __table_args__ = (
        CheckConstraint(
            "(project_id IS NOT NULL) OR (visit_id IS NOT NULL)", name="ck_exports_has_resource"
        ),
        Index("ix_exports_project_visit", "project_id", "visit_id"),
    )

    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    visit_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("visits.id", ondelete="CASCADE"), index=True
    )
    file_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("files.id", ondelete="SET NULL"), index=True
    )
    export_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[ExportStatus] = mapped_column(
        enum_column(ExportStatus, "export_status"), default=ExportStatus.PENDING, nullable=False
    )
    error: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("profiles.id", ondelete="RESTRICT"), nullable=False
    )


class AuditEvent(Base, IdMixin):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_events_workspace_created", "workspace_id", "created_at"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("profiles.id", ondelete="SET NULL"), index=True
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(50))
    resource_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    safe_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class BackupRun(Base, IdMixin):
    __tablename__ = "backup_runs"
    __table_args__ = (Index("ix_backup_runs_started", "started_at"),)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[BackupStatus] = mapped_column(
        enum_column(BackupStatus, "backup_status"), default=BackupStatus.RUNNING, nullable=False
    )
    object_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    byte_count: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    manifest_sha256: Mapped[str | None] = mapped_column(String(64))
    error: Mapped[str | None] = mapped_column(Text)
