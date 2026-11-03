from cryptography.fernet import Fernet

from webapp.cloud.auth.cipher import TokenCipher
from webapp.cloud.auth.client import AuthSession, AuthUser
from webapp.cloud.auth.config import AuthConfig
from webapp.cloud.auth.service import AuthenticationService
from webapp.cloud.db.models import Base
from webapp.cloud.db.session import create_database


def make_service(tmp_path):
    database = create_database(
        "sqlite+pysqlite:///" + (tmp_path / "auth.db").as_posix(),
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(database.engine)
    config = AuthConfig(
        "https://example.supabase.co", "publishable", "tenant",
        "https://sitescribe.example", "admin@example.com", False,
    )
    return AuthenticationService(
        database, config, TokenCipher([Fernet.generate_key().decode()])
    )


def provider_session(user_id, email):
    user = AuthUser(user_id, email, "azure")
    return AuthSession("access", "refresh", 3600, "bearer", user)


def test_bootstrap_admin_and_pending_member_flow(tmp_path):
    service = make_service(tmp_path)
    admin_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    admin = service.establish(
        AuthUser(admin_id, "admin@example.com", "azure"),
        provider_session(admin_id, "admin@example.com"),
    )
    assert (admin.role, admin.status) == ("admin", "active")
    assert service.resolve(admin.opaque_session_id).email == "admin@example.com"

    member_id = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    member = service.establish(
        AuthUser(member_id, "member@example.com", "azure"),
        provider_session(member_id, "member@example.com"),
    )
    assert (member.role, member.status) == ("member", "pending")
    service.revoke(member.opaque_session_id)
    assert service.resolve(member.opaque_session_id) is None
