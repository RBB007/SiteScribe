import io
import json
from pathlib import Path
from uuid import UUID

import pytest

from webapp.cloud.storage import (
    BlobConflictError,
    BlobNotFoundError,
    BlobTransportError,
    BlobValidationError,
    HttpResponse,
    LocalBlobStore,
    SupabaseBlobStore,
    UploadCompensation,
    UploadPolicy,
    build_private_key,
    delete_orphans,
    plan_reconciliation,
    sanitize_filename,
    validate_key,
    validate_upload,
)


IDS = [UUID(int=number) for number in range(1, 5)]


def test_private_key_is_deterministic_and_sanitizes_browser_path():
    key = build_private_key(
        workspace_id=IDS[0],
        project_id=str(IDS[1]),
        visit_id=IDS[2],
        file_id=IDS[3],
        filename=r"C:\fakepath\béam photo (1).JPG",
    )

    assert key == (
        "workspace/00000000-0000-0000-0000-000000000001/"
        "project/00000000-0000-0000-0000-000000000002/"
        "visit/00000000-0000-0000-0000-000000000003/"
        "00000000-0000-0000-0000-000000000004/beam_photo_1_.JPG"
    )


@pytest.mark.parametrize("key", ["", "/root", r"one\two", "one//two", "one/../two"])
def test_validate_key_rejects_unsafe_paths(key):
    with pytest.raises(BlobValidationError):
        validate_key(key)


def test_filename_rejects_values_without_safe_characters():
    with pytest.raises(BlobValidationError):
        sanitize_filename("... ")


def test_upload_validation_is_configurable_and_normalizes_type():
    result = validate_upload(
        filename=" report.PDF ",
        content_type="Application/PDF; charset=binary",
        size=12,
        policy=UploadPolicy(max_bytes=12, allowed_extensions=frozenset({"pdf"})),
    )
    assert result.filename == "report.PDF"
    assert result.content_type == "application/pdf"
    assert result.size == 12

    with pytest.raises(BlobValidationError, match="exceeds"):
        validate_upload(filename="report.pdf", content_type="application/pdf", size=13,
                        policy=UploadPolicy(max_bytes=12))
    with pytest.raises(BlobValidationError, match="content type"):
        validate_upload(filename="payload.exe", content_type="application/octet-stream", size=1)
    with pytest.raises(BlobValidationError, match="empty"):
        validate_upload(filename="report.pdf", content_type="application/pdf", size=0)


def test_local_blob_store_round_trip_sources_and_overwrite(tmp_path):
    store = LocalBlobStore(tmp_path / "private")
    key = "workspace/w/project/p/visit/v/f/photo.jpg"

    created = store.put(key, b"first", content_type="image/jpeg")
    assert created.size == 5
    assert store.stat(key).content_type == "image/jpeg"
    with pytest.raises(BlobConflictError):
        store.put(key, b"collision")

    source = tmp_path / "source.jpg"
    source.write_bytes(b"second")
    store.put(key, source, overwrite=True)
    destination = tmp_path / "nested" / "download.jpg"
    assert store.download_to(key, destination) == destination
    assert destination.read_bytes() == b"second"

    store.put("streams/report.txt", io.BytesIO(b"stream"))
    assert (tmp_path / "private" / "streams" / "report.txt").read_bytes() == b"stream"


def test_local_blob_store_missing_delete_and_short_lived_url(tmp_path):
    store = LocalBlobStore(tmp_path / "private", base_url="https://download.invalid/private")
    store.put("a file.txt", b"data")
    assert store.signed_url("a file.txt", expires_in=60) == (
        "https://download.invalid/private/a%20file.txt?expires_in=60"
    )
    store.delete("a file.txt")
    store.delete("a file.txt")
    with pytest.raises(BlobNotFoundError):
        store.stat("a file.txt")
    with pytest.raises(BlobNotFoundError):
        store.download_to("missing.txt", tmp_path / "out")


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, *, headers, body=None):
        self.calls.append((method, url, dict(headers), body))
        return self.responses.pop(0)


def test_supabase_contract_uses_private_authenticated_routes(tmp_path):
    transport = FakeTransport(
        [
            HttpResponse(200, {}, b'{}'),
            HttpResponse(200, {"Content-Length": "3", "Content-Type": "image/jpeg",
                               "ETag": '"abc"'}, b""),
            HttpResponse(200, {}, b"raw"),
            HttpResponse(200, {}, json.dumps({"signedURL": "/storage/v1/signed/path"}).encode()),
            HttpResponse(200, {}, b""),
        ]
    )
    store = SupabaseBlobStore(
        supabase_url="https://example.supabase.co",
        secret_key="server-secret",
        bucket="project-files",
        transport=transport,
    )
    key = "workspace/w/project/p/visit/v/file/photo 1.jpg"

    assert store.put(key, b"raw", content_type="image/jpeg").size == 3
    metadata = store.stat(key)
    assert (metadata.size, metadata.content_type, metadata.etag) == (3, "image/jpeg", "abc")
    output = tmp_path / "download.jpg"
    store.download_to(key, output)
    assert output.read_bytes() == b"raw"
    assert store.signed_url(key) == "https://example.supabase.co/storage/v1/signed/path"
    store.delete(key)

    methods = [call[0] for call in transport.calls]
    assert methods == ["POST", "HEAD", "GET", "POST", "DELETE"]
    assert "/object/project-files/workspace/w/" in transport.calls[0][1]
    assert "/object/authenticated/project-files/workspace/w/" in transport.calls[1][1]
    assert "/object/sign/project-files/workspace/w/" in transport.calls[3][1]
    assert transport.calls[0][2]["Authorization"] == "Bearer server-secret"
    assert transport.calls[0][2]["x-upsert"] == "false"
    assert json.loads(transport.calls[3][3]) == {"expiresIn": 60}


@pytest.mark.parametrize(
    ("status", "exception"),
    [(404, BlobNotFoundError), (409, BlobConflictError), (500, BlobTransportError)],
)
def test_supabase_maps_remote_errors_without_leaking_secret(status, exception):
    transport = FakeTransport([HttpResponse(status, {}, b'{"message":"failure"}')])
    store = SupabaseBlobStore(
        supabase_url="https://example.supabase.co",
        secret_key="do-not-leak",
        transport=transport,
    )
    with pytest.raises(exception) as caught:
        store.put("safe/key.txt", b"x")
    assert "do-not-leak" not in str(caught.value)


def test_supabase_missing_delete_is_idempotent():
    transport = FakeTransport([HttpResponse(404, {}, b"")])
    store = SupabaseBlobStore(
        supabase_url="https://example.supabase.co", secret_key="secret", transport=transport
    )
    store.delete("already/gone")


class RecordingStore:
    def __init__(self, failing_key=None):
        self.deleted = []
        self.failing_key = failing_key

    def delete(self, key):
        if key == self.failing_key:
            raise RuntimeError("cleanup failed")
        self.deleted.append(key)


def test_upload_compensation_rolls_back_in_reverse_without_masking_error():
    store = RecordingStore(failing_key="one")
    compensation = UploadCompensation(store)
    with pytest.raises(ValueError, match="database"):
        with compensation as uploads:
            uploads.track("one")
            uploads.track("two")
            raise ValueError("database failed")

    assert store.deleted == ["two"]
    assert set(compensation.result.failures) == {"one"}


def test_upload_compensation_keeps_objects_only_after_explicit_commit():
    store = RecordingStore()
    with UploadCompensation(store) as uploads:
        uploads.track("saved")
        uploads.commit()
    assert store.deleted == []


def test_reconciliation_is_a_non_destructive_plan_until_explicitly_applied():
    plan = plan_reconciliation({"present", "missing"}, {"present", "orphan"})
    assert plan.matched == {"present"}
    assert plan.missing == {"missing"}
    assert plan.orphaned == {"orphan"}
    assert not plan.clean

    store = RecordingStore()
    result = delete_orphans(store, plan)
    assert result.deleted == ["orphan"]
    assert store.deleted == ["orphan"]

