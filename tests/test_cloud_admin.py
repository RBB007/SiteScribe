from types import SimpleNamespace

from flask import Flask

from webapp.cloud.admin import create_admin_blueprint, load_secret
from webapp.cloud.storage import LocalBlobStore


class Auth:
    def __init__(self, role):
        self.user = SimpleNamespace(
            role=role, status="active", workspace_id="workspace-1", email="admin@example.com"
        )

    def resolve(self, value):
        return self.user if value == "valid" else None


def client_for(tmp_path, role):
    app = Flask(__name__, template_folder="../webapp/templates")
    app.secret_key = "test"
    store = LocalBlobStore(tmp_path / "objects")
    app.register_blueprint(create_admin_blueprint(Auth(role), store))
    client = app.test_client()
    with client.session_transaction() as session:
        session["cloud_sid"] = "valid"
    return client, store


def test_non_admin_cannot_view_or_update_settings(tmp_path):
    client, _store = client_for(tmp_path, "member")
    assert client.get("/admin").status_code == 403
    assert client.post("/api/admin/settings", data={"api_key": "secret"}).status_code == 403


def test_admin_api_returns_json_when_session_is_missing(tmp_path):
    app = Flask(__name__, template_folder="../webapp/templates")
    app.secret_key = "test"
    app.register_blueprint(create_admin_blueprint(Auth("admin"), LocalBlobStore(tmp_path / "objects")))

    response = app.test_client().get("/api/admin/settings")

    assert response.status_code == 401
    assert response.is_json
    assert response.json["error"] == "authentication required"


def test_admin_stores_encrypted_claude_key(tmp_path, monkeypatch):
    monkeypatch.setenv("FLASK_SECRET_KEY", "unit-test-encryption-secret")
    client, store = client_for(tmp_path, "admin")
    response = client.post("/api/admin/settings", data={"api_key": "sk-ant-private"})
    assert response.status_code == 200
    assert load_secret(store, "workspace-1") == "sk-ant-private"
    status = client.get("/api/admin/settings").json
    assert status == {"secret": True}
