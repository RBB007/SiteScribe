"""End-to-end tests for the photo-entry model and the PR #27 review fixes."""
import io, os, sys, json, zlib, struct, zipfile, tempfile, shutil
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "webapp"))


def _png(w=32, h=32):
    def chunk(tag, data):
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c))
    raw = b"".join(b"\x00" + bytes([(x * 7) % 256, 90, 150][i % 3] for i in range(w * 3))
                   for x in range(h))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


@pytest.fixture
def client():
    tmp = tempfile.mkdtemp()
    os.environ["SITESCRIBE_PIN"] = "2424"
    os.environ["SITESCRIBE_SECRET"] = "test"
    import server
    server.DATA_DIR = os.path.join(tmp, "data")
    server.UPLOADS = os.path.join(tmp, "uploads")
    server.PROJECTS_FILE = os.path.join(server.DATA_DIR, "projects.json")
    os.makedirs(server.DATA_DIR, exist_ok=True)
    os.makedirs(server.UPLOADS, exist_ok=True)
    c = server.app.test_client()
    c.post("/login", data={"pin": "2424"})
    c.post("/api/projects", json={"name": "T"})
    c._server = server
    c._tmp = tmp
    yield c
    shutil.rmtree(tmp, ignore_errors=True)


def upload(c, item, data=None, **extra):
    data = data or {}
    data["photo"] = (io.BytesIO(_png()), "x.png")
    data.update(extra)
    return c.post(f"/api/item/{item}/photo", data=data,
                  content_type="multipart/form-data").get_json()


# --------------------------------------------------------------- structure

def test_item_starts_with_one_empty_entry(client):
    it = client.post("/api/item").get_json()
    assert it["item_id"] == "001"
    assert [e["photo_id"] for e in it["photos"]] == ["001_01"]
    assert it["photos"][0]["filename"] is None


def test_entry_carries_the_incident_fields(client):
    e = client.post("/api/item").get_json()["photos"][0]
    for k in ("description", "importance", "tags", "location", "include", "audio_clips"):
        assert k in e


def test_ids_are_xxx_xx(client):
    client.post("/api/item")
    it = client.post("/api/item").get_json()
    assert it["item_id"] == "002"
    e = client.post("/api/item/002/photo", data={"inherit": "clear"}).get_json()
    assert e["photo_id"] == "002_02"


# --------------------------------------------------------------- keep / clear

def test_keep_copies_details_but_not_media(client):
    client.post("/api/item")
    client.patch("/api/item/001/photo/001_01", json={
        "description": "Spalling", "importance": "Major", "tags": ["c"],
        "location": {"plan_id": "PL-01", "page": 1, "x": 0.4, "y": 0.6}})
    upload(client, "001", photo_id="001_01")
    k = client.post("/api/item/001/photo", data={"inherit": "keep"}).get_json()
    assert k["description"] == "Spalling" and k["importance"] == "Major"
    assert k["tags"] == ["c"] and k["location"]["x"] == pytest.approx(0.4)
    assert k["filename"] is None and k["audio_clips"] == []


def test_clear_starts_blank(client):
    client.post("/api/item")
    client.patch("/api/item/001/photo/001_01", json={"description": "x", "importance": "Major"})
    e = client.post("/api/item/001/photo", data={"inherit": "clear"}).get_json()
    assert e["description"] == "" and e["importance"] == "Info" and e["location"] is None


# --------------------------------------------------------------- review fix 1

def test_upload_targets_the_named_entry(client):
    """PR #27 review 1: an upload must land on the entry the UI is showing."""
    client.post("/api/item")
    client.post("/api/item/001/photo", data={"inherit": "keep"})   # 001_02, also imageless
    e = upload(client, "001", photo_id="001_02")
    assert e["photo_id"] == "001_02"
    visit = client.get("/api/visit").get_json()
    photos = visit["items"][0]["photos"]
    assert photos[0]["filename"] is None, "001_01 must stay empty"
    assert photos[1]["filename"] is not None


def test_upload_without_target_uses_newest_imageless(client):
    client.post("/api/item")
    client.post("/api/item/001/photo", data={"inherit": "clear"})
    e = upload(client, "001")
    assert e["photo_id"] == "001_02"


def test_upload_to_a_filled_entry_is_rejected(client):
    client.post("/api/item")
    upload(client, "001", photo_id="001_01")
    r = client.post("/api/item/001/photo",
                    data={"photo": (io.BytesIO(_png()), "y.png"), "photo_id": "001_01"},
                    content_type="multipart/form-data")
    assert r.status_code == 400


# --------------------------------------------------------------- validation

@pytest.mark.parametrize("body", [
    {"importance": "Nope"},
    {"location": {"plan_id": "PL-01", "page": 1, "x": 5, "y": 0.5}},
    {"location": {"plan_id": "PL-01", "page": 1, "x": -1, "y": 0.5}},
])
def test_bad_patch_is_rejected(client, body):
    client.post("/api/item")
    assert client.patch("/api/item/001/photo/001_01", json=body).status_code == 400


def test_unknown_entry_404(client):
    client.post("/api/item")
    assert client.patch("/api/item/001/photo/001_99", json={"include": False}).status_code == 404


def test_limits(client):
    client.post("/api/item")
    for _ in range(98):
        client.post("/api/item/001/photo", data={"inherit": "clear"})
    assert len(client.get("/api/visit").get_json()["items"][0]["photos"]) == 99
    assert client.post("/api/item/001/photo", data={"inherit": "clear"}).status_code == 400


# --------------------------------------------------------------- audio

def test_audio_attaches_to_the_entry(client):
    client.post("/api/item")
    r = client.post("/api/item/001/photo/001_01/audio",
                    data={"audio": (io.BytesIO(b"\x1aE\xdf\xa3" + os.urandom(500)), "n.webm"),
                          "transcribe": "false"},
                    content_type="multipart/form-data").get_json()
    assert r["clip"]["clip_id"] == "001_01_A01"
    assert r["transcript"] == ""


def test_audio_does_not_overwrite_a_written_description(client):
    client.post("/api/item")
    client.patch("/api/item/001/photo/001_01", json={"description": "typed by hand"})
    client.post("/api/item/001/photo/001_01/audio",
                data={"audio": (io.BytesIO(b"\x1aE\xdf\xa3" + os.urandom(500)), "n.webm"),
                      "transcribe": "false"},
                content_type="multipart/form-data")
    e = client.get("/api/visit").get_json()["items"][0]["photos"][0]
    assert e["description"] == "typed by hand"


# --------------------------------------------------------------- export

def test_export_uses_entry_headings_and_respects_include(client):
    client.post("/api/item")
    client.patch("/api/item/001/photo/001_01", json={"description": "A", "importance": "Major"})
    upload(client, "001", photo_id="001_01")
    client.post("/api/item/001/photo", data={"inherit": "clear"})
    client.patch("/api/item/001/photo/001_02", json={"description": "B", "include": False})
    r = client.get("/api/export/docx")
    assert r.status_code == 200
    doc = zipfile.ZipFile(io.BytesIO(r.data)).read("word/document.xml").decode()
    assert "001_01 — Major" in doc
    assert "001_02" not in doc


def test_entry_without_an_image_exports(client):
    client.post("/api/item")
    client.patch("/api/item/001/photo/001_01", json={"description": "no photo yet"})
    r = client.get("/api/export/docx")
    assert r.status_code == 200
    assert "no photo yet" in zipfile.ZipFile(io.BytesIO(r.data)).read("word/document.xml").decode()


# --------------------------------------------------------------- migration

def _seed_old(server, pid="P-001"):
    d = os.path.join(server.DATA_DIR, pid)
    u = os.path.join(server.UPLOADS, pid, "I-003")
    os.makedirs(d, exist_ok=True)
    os.makedirs(u, exist_ok=True)
    for n in (1, 2):
        open(os.path.join(u, f"I-003-P-0{n}_a.png"), "wb").write(_png())
    open(os.path.join(u, "I-003_audio_01_n.webm"), "wb").write(b"\x1aE\xdf\xa3zz")
    json.dump({"items": [{
        "item_id": "I-003", "description": "shared desc", "importance": "Major",
        "tags": ["t"], "include": True,
        "location": {"plan_id": "PL-01", "page": 1, "x": 0.5, "y": 0.5},
        "audio_clips": [{"clip_id": "I-003-A-01", "filename": "I-003_audio_01_n.webm",
                         "url": f"/uploads/{pid}/I-003/I-003_audio_01_n.webm",
                         "bytes": 6, "transcript": "", "created": "2026-01-01T00:00:00Z"}],
        "created": "2026-01-01T00:00:00Z",
        "photos": [{"photo_id": f"I-003-P-0{n}", "filename": f"I-003-P-0{n}_a.png",
                    "url": f"/uploads/{pid}/I-003/I-003-P-0{n}_a.png", "caption": ""}
                   for n in (1, 2)]}],
        "plans": [], "template": None},
        open(os.path.join(d, "visit.json"), "w"))


def test_migration_copies_details_onto_every_entry(client):
    s = client._server
    _seed_old(s)
    data = s.load("P-001")
    it = data["items"][0]
    assert it["item_id"] == "003"
    assert [e["photo_id"] for e in it["photos"]] == ["003_01", "003_02"]
    for e in it["photos"]:
        assert e["description"] == "shared desc"
        assert e["importance"] == "Major"
        assert e["location"]["x"] == pytest.approx(0.5)


def test_migration_persists_and_is_idempotent(client):
    """PR #27 review 3: the upgrade must be written, not redone on every read."""
    s = client._server
    _seed_old(s)
    s.load("P-001")
    on_disk = json.load(open(os.path.join(s.DATA_DIR, "P-001", "visit.json")))
    assert on_disk["items"][0]["item_id"] == "003", "upgrade must be persisted by load()"
    before = open(os.path.join(s.DATA_DIR, "P-001", "visit.json")).read()
    s.load("P-001")
    assert open(os.path.join(s.DATA_DIR, "P-001", "visit.json")).read() == before


def test_migrated_audio_is_not_shared_between_entries(client):
    """PR #27 review 2: a shared clip file left dangling records on delete."""
    s = client._server
    _seed_old(s)
    it = s.load("P-001")["items"][0]
    assert len(it["photos"][0]["audio_clips"]) == 1
    assert it["photos"][1]["audio_clips"] == [], "clips must not be duplicated across entries"
    names = [c["filename"] for e in it["photos"] for c in e["audio_clips"]]
    assert len(names) == len(set(names))


def test_every_migrated_file_exists_on_disk(client):
    s = client._server
    _seed_old(s)
    it = s.load("P-001")["items"][0]
    for e in it["photos"]:
        if e["filename"]:
            assert os.path.exists(os.path.join(s.UPLOADS, "P-001", "003", e["filename"]))
        for c in e["audio_clips"]:
            assert os.path.exists(os.path.join(s.UPLOADS, "P-001", "003", c["filename"]))
