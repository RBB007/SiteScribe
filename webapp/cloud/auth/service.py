"""Database-backed authentication and one-workspace membership policy."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from webapp.cloud.db.models import (
    MemberRole,
    MemberStatus,
    Profile,
    Workspace,
    WorkspaceMember,
)
from webapp.cloud.db.repositories import AuthSessionRepository
from webapp.cloud.db.session import Database

from .cipher import TokenCipher
from .client import AuthSession, AuthUser
from .config import AuthConfig


class SignInRejected(PermissionError):
    pass


@dataclass(frozen=True)
class SignedInUser:
    profile_id: uuid.UUID
    email: str
    workspace_id: uuid.UUID
    role: str
    status: str
    opaque_session_id: str


class AuthenticationService:
    def __init__(self, database: Database, config: AuthConfig, cipher: TokenCipher):
        self.database = database
        self.config = config
        self.cipher = cipher

    def establish(self, identity: AuthUser, provider_session: AuthSession) -> SignedInUser:
        try:
            profile_id = uuid.UUID(identity.id)
        except (ValueError, TypeError) as exc:
            raise SignInRejected("The identity provider returned an invalid user ID.") from exc
        now = datetime.now(timezone.utc)
        with self.database.transaction() as db:
            profile = db.get(Profile, profile_id)
            if profile is None:
                profile = Profile(id=profile_id, email=identity.email)
                db.add(profile)
                db.flush()
            elif profile.email != identity.email:
                profile.email = identity.email
            profile.last_login_at = now

            workspace = db.scalar(select(Workspace).order_by(Workspace.created_at, Workspace.id))
            is_bootstrap = identity.email == self.config.bootstrap_admin_email
            if workspace is None:
                if not is_bootstrap:
                    raise SignInRejected("An administrator must initialize this workspace first.")
                workspace = Workspace(name="SiteScribe")
                db.add(workspace)
                db.flush()

            membership = db.scalar(
                select(WorkspaceMember).where(
                    WorkspaceMember.workspace_id == workspace.id,
                    WorkspaceMember.profile_id == profile.id,
                )
            )
            if membership is None:
                membership = WorkspaceMember(
                    workspace_id=workspace.id,
                    profile_id=profile.id,
                    role=MemberRole.ADMIN if is_bootstrap else MemberRole.MEMBER,
                    status=MemberStatus.ACTIVE if is_bootstrap else MemberStatus.PENDING,
                )
                db.add(membership)
                db.flush()

            access_expiry = now + timedelta(seconds=provider_session.expires_in)
            issued = AuthSessionRepository(db).issue(
                profile_id=profile.id,
                access_token_ciphertext=self.cipher.encrypt(provider_session.access_token),
                refresh_token_ciphertext=self.cipher.encrypt(provider_session.refresh_token),
                access_token_expires_at=access_expiry,
                session_expires_at=now + timedelta(hours=12),
            )
            return SignedInUser(
                profile.id,
                profile.email,
                workspace.id,
                membership.role.value,
                membership.status.value,
                issued.opaque_session_id,
            )

    def resolve(self, opaque_session_id: str) -> SignedInUser | None:
        if not opaque_session_id:
            return None
        with self.database.transaction() as db:
            record = AuthSessionRepository(db).resolve(opaque_session_id)
            if record is None:
                return None
            membership = db.scalar(
                select(WorkspaceMember)
                .where(WorkspaceMember.profile_id == record.profile_id)
                .order_by(WorkspaceMember.created_at, WorkspaceMember.id)
            )
            if membership is None:
                return None
            return SignedInUser(
                record.profile.id,
                record.profile.email,
                membership.workspace_id,
                membership.role.value,
                membership.status.value,
                opaque_session_id,
            )

    def revoke(self, opaque_session_id: str) -> None:
        if not opaque_session_id:
            return
        with self.database.transaction() as db:
            AuthSessionRepository(db).revoke(opaque_session_id)
