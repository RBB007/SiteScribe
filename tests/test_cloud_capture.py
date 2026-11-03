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


def test_offline_item_create_with_client_ids_is_idempotent(tmp_path):
    client, _store, visit_id = setup_app(tmp_path)
    item_id, observation_id = str(uuid.uuid4()), str(uuid.uuid4())
    body = {"id": item_id, "observation_id": observation_id, "create_observation": True}
    first = client.post(f"/api/visits/{visit_id}/items", json=body)
    assert first.status_code == 201
    assert first.json["id"] == item_id
    assert first.json["observations"][0]["id"] == observation_id
    replay = client.post(f"/api/visits/{visit_id}/items", json=body)
    assert replay.status_code == 200
    assert replay.json["id"] == item_id
    items = client.get(f"/api/visits/{visit_id}/items").json
    assert [value["id"] for value in items] == [item_id]
    assert len(items[0]["observations"]) == 1


def test_offline_items_get_server_numbers_in_sync_order(tmp_path):
    client, _store, visit_id = setup_app(tmp_path)
    online = client.post(f"/api/visits/{visit_id}/items", json={"create_observation": True})
    queued = client.post(
        f"/api/visits/{visit_id}/items",
        json={"id": str(uuid.uuid4()), "observation_id": str(uuid.uuid4())},
    )
    assert (online.json["number"], queued.json["number"]) == (1, 2)
    assert len(queued.json["observations"]) == 1


def test_client_ids_are_validated_and_not_reused_across_visits(tmp_path):
    client, _store, visit_id = setup_app(tmp_path)
    bad = client.post(f"/api/visits/{visit_id}/items", json={"id": "not-a-uuid"})
    assert bad.status_code == 400
    item = client.post(f"/api/visits/{visit_id}/items", json={"create_observation": True}).json
    taken = client.post(
        f"/api/visits/{visit_id}/items",
        json={"id": str(uuid.uuid4()), "observation_id": item["observations"][0]["id"]},
    )
    assert taken.status_code == 409
    other_item = client.post(f"/api/visits/{visit_id}/items").json
    reused = client.post(
        f"/api/visits/{visit_id}/items/{other_item['id']}/observations",
        json={"id": item["observations"][0]["id"]},
    )
    assert reused.status_code == 409


def test_observation_create_with_client_id_is_idempotent(tmp_path):
    client, _store, visit_id = setup_app(tmp_path)
    item = client.post(f"/api/visits/{visit_id}/items").json
    observation_id = str(uuid.uuid4())
    url = f"/api/visits/{visit_id}/items/{item['id']}/observations"
    first = client.post(url, json={"id": observation_id, "description": "Spall"})
    replay = client.post(url, json={"id": observation_id, "description": "Spall"})
    assert (first.status_code, replay.status_code) == (201, 200)
    assert first.json["id"] == replay.json["id"] == observation_id
    items = client.get(f"/api/visits/{visit_id}/items").json
    assert len(items[0]["observations"]) == 1


def test_replayed_upload_returns_existing_file_without_duplicate(tmp_path):
    client, store, visit_id = setup_app(tmp_path)
    item = client.post(f"/api/visits/{visit_id}/items", json={"create_observation": True}).json
    url = f"/api/visits/{visit_id}/observations/{item['observations'][0]['id']}/files"

    def upload(payload, kind="photo"):
        return client.post(url, data={
            "kind": kind, "file": (io.BytesIO(payload), "field.jpg", "image/jpeg"),
        })

    first, replay = upload(b"same-photo"), upload(b"same-photo")
    assert (first.status_code, replay.status_code) == (201, 200)
    assert first.json["id"] == replay.json["id"]
    assert len(store.objects) == 1
    assert upload(b"different-photo").status_code == 201
    assert len(store.objects) == 2
    files = client.get(f"/api/visits/{visit_id}/items").json[0]["observations"][0]["files"]
    assert len(files) == 2
