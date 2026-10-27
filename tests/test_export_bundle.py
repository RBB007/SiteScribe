"""End to end through the Flask test client: capture two items, export the
bundle, and check the zip holds the report, tagged photos and pinned plans."""

import io
import json
import zipfile

import piexif
import pymupdf
import pytest
from piexif.helper import UserComment
from PIL import Image

from webapp import server


@pytest.fixture
def client(tmp_path, monkeypatch):
    data, uploads = tmp_path / "data", tmp_path / "uploads"
    data.mkdir()
    uploads.mkdir()
    monkeypatch.setattr(server, "DATA_DIR", str(data))
    monkeypatch.setattr(server, "UPLOADS", str(uploads))
    monkeypatch.setattr(server, "PROJECTS_FILE", str(data / "projects.json"))
    monkeypatch.setattr(server, "LEGACY_DATA_FILE", str(data / "visit.json"))
    c = server.app.test_client()
    assert c.post("/login", data={"pin": server.PIN}).status_code == 302
    assert c.post("/api/projects", json={"name": "Elm St / Level 2"}).status_code == 200
    return c


def _jpeg(color):
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), color).save(buf, "JPEG")
    buf.seek(0)
    return buf


def _plan_pdf():
    doc = pymupdf.open()
    for _ in range(2):
        doc.new_page(width=1200, height=800)
    return io.BytesIO(doc.tobytes())


def _item(client, **details):
    item = client.post("/api/item").get_json()
    assert client.patch(f"/api/item/{item['item_id']}", json=details).status_code == 200
    return item["item_id"]


def _photo(client, item_id, name, color):
    r = client.post(f"/api/item/{item_id}/photo",
                    data={"photo": (_jpeg(color), name)}, content_type="multipart/form-data")
    assert r.status_code == 200
    return r.get_json()


def _export(client):
    r = client.get("/api/export/bundle")
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.mimetype == "application/zip"
    return r, zipfile.ZipFile(io.BytesIO(r.data))


def _record(zf, name):
    exif = piexif.load(zf.read(name))
    return json.loads(UserComment.load(exif["Exif"][piexif.ExifIFD.UserComment]))


def test_bundle_has_report_tagged_photos_and_pinned_plans(client):
    plan = client.post("/api/plan", data={"plan": (_plan_pdf(), "Framing plans.pdf")},
                       content_type="multipart/form-data").get_json()
    beam = _item(client, description="Cracked beam at C-4", importance="Major", tags=["Crack"],
                 location={"plan_id": plan["plan_id"], "page": 2, "x": 0.5, "y": 0.5})
    p1 = _photo(client, beam, "IMG_1.jpg", "red")
    p2 = _photo(client, beam, "IMG_2.jpg", "blue")
    client.patch(f"/api/item/{beam}/photo/{p2['photo_id']}", json={"caption": "Close-up"})
    left_out = _item(client, description="Duplicate", include=False)
    _photo(client, left_out, "IMG_3.jpg", "green")

    r, zf = _export(client)

    assert "Elm St _ Level 2.zip" in r.headers["Content-Disposition"]
    folder = "Elm St _ Level 2"
    assert sorted(zf.namelist()) == sorted([
        f"{folder}/site_visit_report.docx",
        f"{folder}/photos/{p1['filename']}",
        f"{folder}/photos/{p2['filename']}",
        f"{folder}/plans/Framing plans_page2.png",   # page 1 has no pin, so it is left out
    ])

    first = _record(zf, f"{folder}/photos/{p1['filename']}")
    assert first["number"] == 1
    assert first["severity"] == "Major"
    assert first["tags"] == ["Crack"]
    assert first["description"] == "Cracked beam at C-4"
    assert first["pin"]["x"] == 0.5
    second = _record(zf, f"{folder}/photos/{p2['filename']}")
    assert second["description"] == "Cracked beam at C-4 — Close-up"
    # each photo keeps its own pixels
    with Image.open(zf.open(f"{folder}/photos/{p2['filename']}")) as image:
        r_, g_, b_ = image.convert("RGB").getpixel((32, 24))
        assert b_ > 200 and r_ < 60

    with Image.open(zf.open(f"{folder}/plans/Framing plans_page2.png")) as image:
        w, h = image.size
        # halfway out from the centre: inside the pin, clear of the number and the white rim
        r_, g_, b_ = image.convert("RGB").getpixel((w // 2, h // 2 + round(min(w, h) * 0.018) * 2 // 3))
        assert (r_, g_, b_) == (0xF2, 0x99, 0x4A)   # Major = orange pin


def test_bundle_without_plans_or_photos_still_has_report(client):
    _item(client, description="Note only")

    _, zf = _export(client)

    assert [n.split("/", 1)[1] for n in zf.namelist()] == ["site_visit_report.docx"]


def test_docx_export_unchanged(client):
    _item(client, description="Note only")

    r = client.get("/api/export/docx")

    assert r.status_code == 200
    assert r.data[:2] == b"PK"
