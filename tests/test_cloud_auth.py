from urllib.parse import parse_qs, urlparse

import pytest

from webapp.cloud.auth.client import AuthError, SupabaseAuthClient
from webapp.cloud.auth.config import AuthConfig
from webapp.cloud.auth.pkce import create_pkce_pair


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload

    @property
    def ok(self):
        return 200 <= self.status_code < 300


class FakeHttp:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self.responses.pop(0)

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return self.responses.pop(0)


def config():
    return AuthConfig(
        supabase_url="https://example.supabase.co",
        publishable_key="publishable",
        azure_tenant_id="tenant",
        app_base_url="https://sitescribe.example",
        bootstrap_admin_email="admin@example.com",
        cookie_secure=True,
    )


def test_pkce_pair_and_authorize_url_are_well_formed():
    pair = create_pkce_pair()
    assert len(pair.verifier) >= 43
    assert "=" not in pair.challenge

    client = SupabaseAuthClient(config(), FakeHttp([]))
    url = client.authorization_url(pair)
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    assert parsed.path == "/auth/v1/authorize"
    assert query["provider"] == ["azure"]
    assert query["state"] == [pair.state]
    assert query["code_challenge_method"] == ["s256"]
    assert query["redirect_to"] == [config().callback_url]


def test_exchange_refresh_and_user_requests():
    payload = {
        "access_token": "access",
        "refresh_token": "refresh",
        "expires_in": 3600,
        "user": {"id": "user-id", "email": "person@example.com"},
    }
    http = FakeHttp(
        [
            FakeResponse(payload=payload),
            FakeResponse(payload=payload),
            FakeResponse(payload={"id": "user-id", "email": "person@example.com"}),
        ]
    )
    client = SupabaseAuthClient(config(), http)

    session = client.exchange_code("code", "verifier")
    assert session.user.email == "person@example.com"
    client.refresh("refresh")
    user = client.user("access")
    assert user.id == "user-id"

    first = http.calls[0]
    assert first[2]["json"]["auth_code"] == "code"
    assert http.calls[2][2]["headers"]["Authorization"] == "Bearer access"


def test_password_sign_in_normalizes_email_and_uses_password_grant():
    payload = {
        "access_token": "access",
        "refresh_token": "refresh",
        "expires_in": 3600,
        "user": {"id": "user-id", "email": "person@example.com"},
    }
    http = FakeHttp([FakeResponse(payload=payload)])
    session = SupabaseAuthClient(config(), http).password_sign_in(
        " Person@Example.com ", "trial-password"
    )
    assert session.user.email == "person@example.com"
    method, url, options = http.calls[0]
    assert method == "POST"
    assert url.endswith("/auth/v1/token?grant_type=password")
    assert options["json"] == {
        "email": "person@example.com",
        "password": "trial-password",
    }


def test_auth_failure_does_not_expose_provider_body():
    http = FakeHttp([FakeResponse(status_code=401, payload={"secret": "do not leak"})])
    client = SupabaseAuthClient(config(), http)
    with pytest.raises(AuthError, match="Authentication failed"):
        client.exchange_code("bad", "verifier")
