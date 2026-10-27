"""End to end through the Flask test client: capture entries, export the
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


def _item(client):
    """A new item; returns (item_id, id of the entry waiting for its image)."""
    item = client.post("/api/item").get_json()
    return item["item_id"], item["photos"][0]["photo_id"]


def _details(client, item_id, photo_id, **details):
    r = client.patch(f"/api/item/{item_id}/photo/{photo_id}", json=details)
    assert r.status_code == 200, r.get_data(as_text=True)


def _photo(client, item_id, name, color, **form):
    r = client.post(f"/api/item/{item_id}/photo", content_type="multipart/form-data",
                    data={"photo": (_jpeg(color), name), **form})
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()


def _export(client):
    r = client.get("/api/export/bundle")
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.mimetype == "application/zip"
    return r, zipfile.ZipFile(io.BytesIO(r.data))


def _record(zf, name):
    exif = piexif.load(zf.read(name))
    return json.loads(UserComment.load(exif["Exif"][piexif.ExifIFD.UserComment]))


def _pin_color(zf, name, x, y):
    with Image.open(zf.open(name)) as image:
        w, h = image.size
        # halfway out from the centre: inside the pin, clear of the number and the white rim
        offset = round(min(w, h) * 0.018) * 2 // 3
        return image.convert("RGB").getpixel((round(x * w), round(y * h) + offset))


def test_bundle_has_report_tagged_photos_and_pinned_plans(client):
    plan = client.post("/api/plan", data={"plan": (_plan_pdf(), "Framing plans.pdf")},
                       content_type="multipart/form-data").get_json()
    on_page2 = {"plan_id": plan["plan_id"], "page": 2, "x": 0.5, "y": 0.5}

    beam, first_id = _item(client)
    _details(client, beam, first_id, description="Cracked beam at C-4", importance="Major",
             tags=["Crack"], location=on_page2)
    first = _photo(client, beam, "IMG_1.jpg", "red")
    # Keep: a second view of the same defect, same details and spot
    second = _photo(client, beam, "IMG_2.jpg", "blue", inherit="keep")
    _details(client, beam, second["photo_id"], caption="Close-up")
    # Clear: a different incident in the same item, pinned but no image yet
    waiting = client.post(f"/api/item/{beam}/photo", json={"inherit": "clear"}).get_json()
    _details(client, beam, waiting["photo_id"], description="Rust at base plate",
             importance="Safety", location={"plan_id": plan["plan_id"], "page": 1, "x": 0.25, "y": 0.5})

    left_out, left_out_id = _item(client)
    _details(client, left_out, left_out_id, description="Duplicate", include=False)
    _photo(client, left_out, "IMG_3.jpg", "green")

    r, zf = _export(client)

    assert "Elm St _ Level 2.zip" in r.headers["Content-Disposition"]
    folder = "Elm St _ Level 2"
    assert sorted(zf.namelist()) == sorted([
        f"{folder}/site_visit_report.docx",
        f"{folder}/photos/{first['filename']}",
        f"{folder}/photos/{second['filename']}",
        f"{folder}/plans/Framing plans_page1.png",
        f"{folder}/plans/Framing plans_page2.png",
    ])

    record = _record(zf, f"{folder}/photos/{first['filename']}")
    assert record["number"] == 1
    assert record["id"] == first["photo_id"]
    assert record["severity"] == "Major"
    assert record["tags"] == ["Crack"]
    assert record["description"] == "Cracked beam at C-4"
    assert record["pin"]["x"] == 0.5
    kept = _record(zf, f"{folder}/photos/{second['filename']}")
    assert kept["severity"] == "Major"
    assert kept["description"] == "Cracked beam at C-4 — Close-up"
    # each photo keeps its own pixels
    with Image.open(zf.open(f"{folder}/photos/{second['filename']}")) as image:
        red, _, blue = image.convert("RGB").getpixel((32, 24))
        assert blue > 200 and red < 60

    assert _pin_color(zf, f"{folder}/plans/Framing plans_page2.png", 0.5, 0.5) == (0xF2, 0x99, 0x4A)
    assert _pin_color(zf, f"{folder}/plans/Framing plans_page1.png", 0.25, 0.5) == (0x9B, 0x51, 0xE0)


def test_every_floor_plan_gets_its_own_image_even_with_the_same_name(client):
    uploads = [("Level 1.pdf", "Info", 0.2), ("Plans.pdf", "Minor", 0.4),
               ("plans.pdf", "Critical", 0.6), ("Plans.pdf", "Safety", 0.8)]
    for name, importance, x in uploads:
        plan = client.post("/api/plan", data={"plan": (_plan_pdf(), name)},
                           content_type="multipart/form-data").get_json()
        item_id, photo_id = _item(client)
        _details(client, item_id, photo_id, importance=importance,
                 location={"plan_id": plan["plan_id"], "page": 1, "x": x, "y": 0.5})

    _, zf = _export(client)

    folder = "Elm St _ Level 2"
    plan_images = sorted(n for n in zf.namelist() if "/plans/" in n)
    assert plan_images == sorted(f"{folder}/plans/{n}" for n in [
        "Level 1_page1.png", "Plans_page1.png", "plans (2)_page1.png", "Plans (3)_page1.png"])
    assert len(set(n.lower() for n in zf.namelist())) == len(zf.namelist())
    # each image carries its own floor's pin, not another plan's
    expected = {"Plans_page1.png": (0.4, (0x27, 0xAE, 0x60)),
                "plans (2)_page1.png": (0.6, (0xEB, 0x57, 0x57)),
                "Plans (3)_page1.png": (0.8, (0x9B, 0x51, 0xE0))}
    for name, (x, color) in expected.items():
        assert _pin_color(zf, f"{folder}/plans/{name}", x, 0.5) == color
        assert _pin_color(zf, f"{folder}/plans/{name}", 0.2, 0.5) == (255, 255, 255)


def test_bundle_without_plans_or_photos_still_has_report(client):
    item_id, photo_id = _item(client)
    _details(client, item_id, photo_id, description="Note only")

    _, zf = _export(client)

    assert [n.split("/", 1)[1] for n in zf.namelist()] == ["site_visit_report.docx"]


def test_docx_export_unchanged(client):
    item_id, photo_id = _item(client)
    _details(client, item_id, photo_id, description="Note only")

    r = client.get("/api/export/docx")

    assert r.status_code == 200
    assert r.data[:2] == b"PK"
