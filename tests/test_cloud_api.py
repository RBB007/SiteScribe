import uuid
from types import SimpleNamespace

from flask import Flask

from webapp.cloud.api import create_api_blueprint
from webapp.cloud.db.models import Base, MemberRole, MemberStatus, Profile, Workspace, WorkspaceMember
from webapp.cloud.db.session import create_database


class FakeAuth:
    def __init__(self, user):
        self.user = user

    def resolve(self, opaque_id):
        return self.user if opaque_id == "valid" else None


def make_app(tmp_path):
    database = create_database(
        "sqlite+pysqlite:///" + (tmp_path / "api.db").as_posix(),
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(database.engine)
    profile_id = uuid.uuid4()
    with database.transaction() as db:
        workspace = Workspace(name="MKA")
        profile = Profile(id=profile_id, email="admin@example.com")
        db.add_all([workspace, profile])
        db.flush()
        db.add(WorkspaceMember(
            workspace_id=workspace.id,
            profile_id=profile.id,
            role=MemberRole.ADMIN,
            status=MemberStatus.ACTIVE,
        ))
        workspace_id = workspace.id
    user = SimpleNamespace(
        profile_id=profile_id, workspace_id=workspace_id,
        email="admin@example.com", role="admin", status="active",
    )
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.register_blueprint(create_api_blueprint(database, FakeAuth(user)))
    return app


def signed_in(client):
    with client.session_transaction() as session:
        session["cloud_sid"] = "valid"


def test_project_and_visit_lifecycle_and_sorting(tmp_path):
    client = make_app(tmp_path).test_client()
    signed_in(client)

    for name in ("zeta", "Alpha"):
        response = client.post("/api/projects", json={"name": name})
        assert response.status_code == 201
        if name == "Alpha":
            project_id = response.json["id"]

    assert [item["name"] for item in client.get("/api/projects").json] == ["Alpha", "zeta"]

    for visit_date in ("2026-01-01", "2026-04-03"):
        response = client.post(
            f"/api/projects/{project_id}/visits",
            json={"visit_date": visit_date, "report_number": visit_date[-2:]},
        )
        assert response.status_code == 201
        visit_id = response.json["id"]
    visits = client.get(f"/api/projects/{project_id}/visits").json
    assert [item["visit_date"] for item in visits] == ["2026-04-03", "2026-01-01"]

    archived = client.delete(f"/api/projects/{project_id}/visits/{visit_id}")
    assert archived.json["purge_after"] is not None
    restored = client.post(f"/api/projects/{project_id}/visits/{visit_id}/restore")
    assert restored.json["purge_after"] is None


def test_api_requires_server_side_session(tmp_path):
    response = make_app(tmp_path).test_client().get("/api/projects")
    assert response.status_code == 401


def test_invalid_cross_resource_id_is_hidden(tmp_path):
    client = make_app(tmp_path).test_client()
    signed_in(client)
    response = client.get(f"/api/projects/{uuid.uuid4()}")
    assert response.status_code == 404
