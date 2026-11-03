import io
import json
import zipfile
from datetime import datetime, timezone

import pytest

from webapp.cloud.archive import (
    ArchiveAsset,
    ArchiveIntegrityError,
    ArchivePathError,
    build_archive,
    parse_archive,
)


EXPORTED_AT = datetime(2026, 11, 2, 18, 30, tzinfo=timezone.utc)


def _records():
    project = {
        "id": "project-1",
        "name": "UNR / Engineering",
        "project_number": "24-100",
    }
    visit = {
        "id": "visit-1",
        "visit_date": "2026-11-01",
        "items": [{
            "item_id": "I-001",
            "photos": [
                {"photo_id": "included", "include": True, "description": "Crack"},
                {"photo_id": "excluded", "include": False, "description": "Duplicate"},
            ],
        }],
    }
    return project, [visit]


def test_complete_archive_round_trips_every_asset_class(tmp_path):
    project, visits = _records()
    plan = tmp_path / "plans.pdf"
    plan.write_bytes(b"%PDF-original-plan")
    audio = io.BytesIO(b"audio-original")
    assets = [
        ArchiveAsset("visit-1", "photos/originals/included/IMG_1.jpg", b"included-photo", "photo", True,
                     "IMG_1.jpg", "image/jpeg", "file-photo-1"),
        ArchiveAsset("visit-1", "photos/originals/excluded/IMG_2.jpg", b"excluded-photo", "photo", False),
        ArchiveAsset("visit-1", "photos/report-ready/IMG_1.jpg", b"processed-photo", "report_photo", True),
        ArchiveAsset("visit-1", "audio/note.m4a", audio, "audio", original_filename="field note.m4a"),
        ArchiveAsset("visit-1", "audio/note.txt", b"transcript", "transcript"),
        ArchiveAsset("visit-1", "plans/originals/plans.pdf", plan, "plan_original"),
        ArchiveAsset("visit-1", "plans/marked/plans_page1.png", b"marked-plan", "plan_marked"),
        ArchiveAsset("visit-1", "template/MKA.docx", b"template-docx", "template"),
        ArchiveAsset("visit-1", "reports/site_visit_report.docx", b"report-docx", "report"),
        ArchiveAsset("visit-1", "exports/raw-data.zip", b"prior-export", "export"),
    ]

    raw = build_archive(project, visits, assets, exported_at=EXPORTED_AT, app_version="1.2.3")
    parsed = parse_archive(raw)

    assert parsed.root == "UNR _ Engineering"
    assert parsed.project == project
    assert parsed.visits == tuple(visits)
    assert len(parsed.assets) == len(assets)
    assert parsed.assets["visits/2026-11-01_visit-1/photos/originals/included/IMG_1.jpg"] == b"included-photo"
    assert parsed.assets["visits/2026-11-01_visit-1/photos/originals/excluded/IMG_2.jpg"] == b"excluded-photo"
    assert parsed.assets["visits/2026-11-01_visit-1/audio/note.m4a"] == b"audio-original"
    assert audio.tell() == 0
    manifest_assets = {item["path"]: item for item in parsed.manifest["assets"]}
    included = manifest_assets["visits/2026-11-01_visit-1/photos/originals/included/IMG_1.jpg"]
    excluded = manifest_assets["visits/2026-11-01_visit-1/photos/originals/excluded/IMG_2.jpg"]
    assert included["included"] is True
    assert included["original_filename"] == "IMG_1.jpg"
    assert included["storage_id"] == "file-photo-1"
    assert excluded["included"] is False
    assert parsed.manifest["counts"] == {
        "visits": 1,
        "assets": 10,
        "files": 13,
        "bytes": sum(item["size"] for item in parsed.manifest["files"]),
    }
    assert "Verify integrity" in parsed.readme


def test_archive_output_is_deterministic_and_members_are_canonical():
    project, visits = _records()
    assets = [ArchiveAsset("visit-1", "reports/report.docx", b"docx", "report")]

    first = build_archive(project, visits, assets, exported_at=EXPORTED_AT, app_version="test")
    second = build_archive(project, visits, reversed(assets), exported_at=EXPORTED_AT, app_version="test")

    assert first == second
    with zipfile.ZipFile(io.BytesIO(first)) as archive:
        assert archive.namelist() == sorted(archive.namelist())
        assert all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in archive.infolist())
        assert archive.namelist()[-1].endswith("visits/2026-11-01_visit-1/visit.json")


@pytest.mark.parametrize("path", [
    "../secret.txt",
    "/absolute.txt",
    "C:/secret.txt",
    "photos\\image.jpg",
    "photos/../../secret.txt",
    "photos/\x00image.jpg",
])
def test_builder_rejects_unsafe_asset_paths(path):
    project, visits = _records()
    with pytest.raises(ArchivePathError):
        build_archive(project, visits, [ArchiveAsset("visit-1", path, b"x", "photo")], exported_at=EXPORTED_AT)


def test_builder_rejects_case_insensitive_duplicate_asset_paths():
    project, visits = _records()
    assets = [
        ArchiveAsset("visit-1", "photos/IMG.jpg", b"first", "photo"),
        ArchiveAsset("visit-1", "photos/img.JPG", b"second", "photo"),
    ]
    with pytest.raises(ArchivePathError, match="duplicate"):
        build_archive(project, visits, assets, exported_at=EXPORTED_AT)


def test_parser_rejects_checksum_tampering():
    project, visits = _records()
    raw = build_archive(project, visits, exported_at=EXPORTED_AT)

    tampered = _rewrite(raw, {"project.json": json.dumps({"id": "attacker"}).encode()})

    with pytest.raises(ArchiveIntegrityError, match="checksum mismatch"):
        parse_archive(tampered)


def test_parser_rejects_zip_slip_member_even_before_integrity_validation():
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("safe/../escape.txt", b"bad")

    with pytest.raises(ArchivePathError):
        parse_archive(output.getvalue())


def test_visit_archive_requires_exactly_one_visit():
    project, visits = _records()
    with pytest.raises(ValueError, match="exactly one"):
        build_archive(project, [], archive_kind="visit", exported_at=EXPORTED_AT)
    raw = build_archive(project, visits, archive_kind="visit", exported_at=EXPORTED_AT)
    assert parse_archive(raw).manifest["archive_kind"] == "visit"


def _rewrite(raw: bytes, replacements: dict[str, bytes]) -> bytes:
    source = zipfile.ZipFile(io.BytesIO(raw))
    output = io.BytesIO()
    with source, zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as target:
        for info in source.infolist():
            relative = info.filename.split("/", 1)[1]
            target.writestr(info.filename, replacements.get(relative, source.read(info)))
    return output.getvalue()
