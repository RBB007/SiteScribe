import io
import uuid
from datetime import date
from types import SimpleNamespace

from flask import Flask

from webapp.cloud.capture import create_capture_blueprint
from webapp.cloud.db.models import Base, Profile, Project, Visit, Workspace
from webapp.cloud.db.session import create_database


class Auth:
    def __init__(self, user):
        self.user = user

    def resolve(self, value):
        return self.user if value == "valid" else None


class Store:
    def __init__(self):
        self.objects = {}

    def put(self, key, payload, **_kwargs):
        self.objects[key] = payload

    def delete(self, key):
        self.objects.pop(key, None)


def setup_app(tmp_path):
    db = create_database(
        "sqlite+pysqlite:///" + (tmp_path / "capture.db").as_posix(),
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(db.engine)
    profile_id = uuid.uuid4()
    with db.transaction() as session:
        workspace = Workspace(name="MKA")
        profile = Profile(id=profile_id, email="user@example.com")
        session.add_all([workspace, profile])
        session.flush()
        project = Project(workspace_id=workspace.id, name="Tower")
        session.add(project)
        session.flush()
        visit = Visit(project_id=project.id, visit_date=date(2026, 4, 5))
        session.add(visit)
        session.flush()
        ids = workspace.id, visit.id
    user = SimpleNamespace(
        workspace_id=ids[0], profile_id=profile_id, status="active",
        email="user@example.com", role="member",
    )
    app = Flask(__name__)
    app.secret_key = "test"
    store = Store()
    app.register_blueprint(create_capture_blueprint(db, Auth(user), store))
    client = app.test_client()
    with client.session_transaction() as session:
        session["cloud_sid"] = "valid"
    return client, store, ids[1]


def test_explicit_visit_capture_and_private_upload(tmp_path):
    client, store, visit_id = setup_app(tmp_path)
    item = client.post(f"/api/visits/{visit_id}/items")
    assert item.status_code == 201
    observation = client.post(
        f"/api/visits/{visit_id}/items/{item.json['id']}/observations",
        json={"description": "Crack at grid A", "include_in_report": False},
    )
    assert observation.status_code == 201
    uploaded = client.post(
        f"/api/visits/{visit_id}/observations/{observation.json['id']}/files",
        data={
            "kind": "photo",
            "file": (io.BytesIO(b"jpeg-data"), "field.jpg", "image/jpeg"),
        },
    )
    assert uploaded.status_code == 201
    assert uploaded.json["download_url"].startswith("/api/files/")
    assert list(store.objects.values()) == [b"jpeg-data"]


def test_visit_overview_and_atomic_new_item(tmp_path):
    client, _store, visit_id = setup_app(tmp_path)
    created = client.post(
        f"/api/visits/{visit_id}/items", json={"create_observation": True}
    )
    assert created.status_code == 201
    assert len(created.json["observations"]) == 1
    observation = created.json["observations"][0]
    updated = client.patch(
        f"/api/visits/{visit_id}/observations/{observation['id']}",
        json={"description": "[Observation summary]", "severity": "Critical"},
    )
    assert updated.status_code == 200

    overview = client.get(f"/api/visits/{visit_id}/overview")
    assert overview.status_code == 200
    assert overview.json["project"]["name"] == "Tower"
    assert overview.json["stats"] == {"items": 1, "included": 1, "critical": 1}
    assert overview.json["items"][0]["observations"][0]["files"] == []


def test_deleting_item_removes_its_private_files(tmp_path):
    client, store, visit_id = setup_app(tmp_path)
    item = client.post(
        f"/api/visits/{visit_id}/items", json={"create_observation": True}
    ).json
    observation_id = item["observations"][0]["id"]
    client.post(
        f"/api/visits/{visit_id}/observations/{observation_id}/files",
        data={"kind": "photo", "file": (io.BytesIO(b"photo"), "field.jpg", "image/jpeg")},
    )
    assert store.objects

    deleted = client.delete(f"/api/visits/{visit_id}/items/{item['id']}")
    assert deleted.status_code == 204
    assert store.objects == {}
    assert client.get(f"/api/visits/{visit_id}/items").json == []
