import uuid
from types import SimpleNamespace

from flask import Flask

from webapp.cloud.auth.blueprint import create_auth_blueprint
from webapp.cloud.auth.client import AuthError


class Client:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = []

    def password_sign_in(self, email, password):
        self.calls.append((email, password))
        if self.fail:
            raise AuthError("provider detail must stay hidden")
        return SimpleNamespace(user=SimpleNamespace(email=email))


class Service:
    def establish(self, _user, _provider_session):
        return SimpleNamespace(
            profile_id=uuid.uuid4(),
            workspace_id=uuid.uuid4(),
            email="admin@example.com",
            role="admin",
            status="active",
            opaque_session_id="opaque-session",
        )

    def resolve(self, _session_id):
        return None

    def revoke(self, _session_id):
        return None


def app_for(client):
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(create_auth_blueprint(client, Service()))
    return app


def test_trial_login_renders_password_form_and_establishes_session():
    provider = Client()
    client = app_for(provider).test_client()
    assert client.get("/auth/login").status_code == 200
    response = client.post(
        "/auth/login",
        data={"email": "admin@example.com", "password": "trial-password"},
    )
    assert response.status_code == 302
    assert response.headers["Location"] == "/"
    assert provider.calls == [("admin@example.com", "trial-password")]
    with client.session_transaction() as browser_session:
        assert browser_session["cloud_sid"] == "opaque-session"


def test_trial_login_hides_provider_failure_details():
    response = app_for(Client(fail=True)).test_client().post(
        "/auth/login",
        data={"email": "admin@example.com", "password": "bad"},
    )
    assert response.status_code == 401
    assert b"Incorrect email or password" in response.data
    assert b"provider detail" not in response.data
