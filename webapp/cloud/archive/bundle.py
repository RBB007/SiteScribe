"""Build and verify the complete, portable SiteScribe archive format."""

from __future__ import annotations

import hashlib
import io
import json
import mimetypes
import re
import stat
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timezone
from os import PathLike
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, Iterable, Mapping, Sequence
from uuid import UUID

ARCHIVE_SCHEMA_VERSION = 1
_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
_CONTROL_FILES = {"archive_manifest.json", "README.txt", "project.json", "checksums.sha256"}
_SAFE_COMPONENT = re.compile(r"[^A-Za-z0-9 ._()-]+")


class ArchiveError(ValueError):
    """Base class for archive contract errors."""


class ArchivePathError(ArchiveError):
    """An archive member name is unsafe or conflicts with another member."""


class ArchiveIntegrityError(ArchiveError):
    """An archive is malformed, incomplete, or fails an integrity check."""


@dataclass(frozen=True)
class ArchiveAsset:
    """One visit asset to preserve in the archive.

    ``relative_path`` is relative to that visit's directory, for example
    ``photos/originals/included/IMG_001.jpg`` or ``audio/note.m4a``.
    ``source`` may be bytes, a local path, or a binary stream.  Metadata is
    copied into the manifest so a restore does not depend on EXIF data.
    """

    visit_id: str
    relative_path: str
    source: bytes | bytearray | memoryview | str | PathLike[str] | BinaryIO
    kind: str
    included: bool | None = None
    original_filename: str | None = None
    mime_type: str | None = None
    storage_id: str | None = None


@dataclass(frozen=True)
class ArchiveContents:
    """A verified archive decoded into structured records and asset bytes."""

    root: str
    manifest: dict[str, Any]
    project: dict[str, Any]
    visits: tuple[dict[str, Any], ...]
    assets: dict[str, bytes]
    readme: str


def build_archive(
    project: Mapping[str, Any],
    visits: Sequence[Mapping[str, Any]],
    assets: Iterable[ArchiveAsset] = (),
    *,
    exported_at: datetime | str | None = None,
    app_version: str = "unknown",
    archive_kind: str = "project",
) -> bytes:
    """Return a deterministic complete-archive ZIP.

    Identical inputs (including ``exported_at``) produce identical bytes.  A
    caller that omits ``exported_at`` gets the current UTC time, as expected
    for a user-facing export.
    """

    if archive_kind not in {"project", "visit"}:
        raise ArchiveError("archive_kind must be 'project' or 'visit'")
    if archive_kind == "visit" and len(visits) != 1:
        raise ArchiveError("a visit archive must contain exactly one visit")

    project_data = dict(project)
    project_id = _record_id(project_data, "project")
    root = _safe_component(str(project_data.get("name") or "SiteScribe Archive"), "archive root")
    visit_records: dict[str, tuple[str, dict[str, Any]]] = {}
    entries: dict[str, bytes] = {
        "README.txt": _readme().encode("utf-8"),
        "project.json": _json_bytes(project_data),
    }

    for raw_visit in visits:
        visit = dict(raw_visit)
        visit_id = _record_id(visit, "visit")
        if visit_id in visit_records:
            raise ArchiveError(f"duplicate visit id: {visit_id}")
        visit_date = str(visit.get("visit_date") or visit.get("date") or "undated")
        folder = _safe_component(f"{visit_date}_{visit_id}", "visit folder")
        if any(existing.casefold() == folder.casefold() for existing, _ in visit_records.values()):
            raise ArchivePathError(f"visit folders collide: {folder}")
        visit_records[visit_id] = (folder, visit)
        entries[f"visits/{folder}/visit.json"] = _json_bytes(visit)

    asset_manifest: list[dict[str, Any]] = []
    for asset in assets:
        visit_id = str(asset.visit_id)
        if visit_id not in visit_records:
            raise ArchiveError(f"asset references unknown visit: {visit_id}")
        relative = _safe_relative_path(asset.relative_path)
        if relative in _CONTROL_FILES or relative.endswith("/visit.json"):
            raise ArchivePathError(f"reserved asset path: {relative}")
        folder, _ = visit_records[visit_id]
        archive_path = f"visits/{folder}/{relative}"
        _ensure_unique(entries, archive_path)
        payload = _read_source(asset.source)
        entries[archive_path] = payload
        asset_manifest.append({
            "path": archive_path,
            "visit_id": visit_id,
            "kind": str(asset.kind),
            "included": asset.included,
            "original_filename": asset.original_filename or PurePosixPath(relative).name,
            "mime_type": asset.mime_type or mimetypes.guess_type(relative)[0] or "application/octet-stream",
            "storage_id": asset.storage_id,
            "size": len(payload),
            "sha256": _sha256(payload),
        })

    content_files = [_file_record(path, payload) for path, payload in sorted(entries.items())]
    timestamp = _export_timestamp(exported_at)
    manifest = {
        "schema_version": ARCHIVE_SCHEMA_VERSION,
        "archive_kind": archive_kind,
        "exported_at": timestamp,
        "app_version": str(app_version),
        "project_id": project_id,
        "visits": [
            {"id": visit_id, "path": f"visits/{folder}/visit.json"}
            for visit_id, (folder, _) in sorted(visit_records.items())
        ],
        "assets": sorted(asset_manifest, key=lambda item: item["path"]),
        "files": content_files,
        "counts": {
            "visits": len(visit_records),
            "assets": len(asset_manifest),
            "files": len(content_files),
            "bytes": sum(item["size"] for item in content_files),
        },
    }
    entries["archive_manifest.json"] = _json_bytes(manifest)
    checksum_lines = [f"{_sha256(payload)}  {path}\n" for path, payload in sorted(entries.items())]
    entries["checksums.sha256"] = "".join(checksum_lines).encode("utf-8")

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for relative_path, payload in sorted(entries.items()):
            info = zipfile.ZipInfo(f"{root}/{relative_path}", date_time=_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            info.create_system = 3
            archive.writestr(info, payload, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return output.getvalue()


def parse_archive(source: bytes | bytearray | memoryview | str | PathLike[str] | BinaryIO) -> ArchiveContents:
    """Parse an archive only after validating paths, manifest, and hashes."""

    raw = _read_source(source)
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw), "r")
    except (zipfile.BadZipFile, OSError) as exc:
        raise ArchiveIntegrityError("not a valid ZIP archive") from exc

    with archive:
        members = archive.infolist()
        if not members:
            raise ArchiveIntegrityError("archive is empty")
        seen: set[str] = set()
        roots: set[str] = set()
        relative_members: dict[str, zipfile.ZipInfo] = {}
        for member in members:
            if member.is_dir():
                continue
            path = _safe_relative_path(member.filename)
            folded = path.casefold()
            if folded in seen:
                raise ArchivePathError(f"duplicate archive member: {path}")
            seen.add(folded)
            if stat.S_ISLNK(member.external_attr >> 16):
                raise ArchivePathError(f"symbolic links are not allowed: {path}")
            parts = PurePosixPath(path).parts
            if len(parts) < 2:
                raise ArchivePathError("every archive member must be below one root folder")
            roots.add(parts[0])
            relative_members["/".join(parts[1:])] = member
        if len(roots) != 1:
            raise ArchivePathError("archive must contain exactly one root folder")
        root = next(iter(roots))
        for required in _CONTROL_FILES:
            if required not in relative_members:
                raise ArchiveIntegrityError(f"missing required file: {required}")

        payloads = {path: archive.read(info) for path, info in relative_members.items()}
        expected_checksums = _parse_checksums(payloads["checksums.sha256"])
        checkable = set(payloads) - {"checksums.sha256"}
        if set(expected_checksums) != checkable:
            raise ArchiveIntegrityError("checksum file list does not match archive contents")
        for path, expected in expected_checksums.items():
            if _sha256(payloads[path]) != expected:
                raise ArchiveIntegrityError(f"checksum mismatch: {path}")

        manifest = _load_object(payloads["archive_manifest.json"], "archive_manifest.json")
        if manifest.get("schema_version") != ARCHIVE_SCHEMA_VERSION:
            raise ArchiveIntegrityError("unsupported archive schema version")
        project = _load_object(payloads["project.json"], "project.json")
        _validate_manifest(manifest, payloads)
        visit_records: list[dict[str, Any]] = []
        for record in manifest.get("visits", []):
            path = record.get("path")
            if not isinstance(path, str) or path not in payloads:
                raise ArchiveIntegrityError("manifest references a missing visit record")
            visit_records.append(_load_object(payloads[path], path))

        asset_paths = [item["path"] for item in manifest.get("assets", [])]
        assets = {path: payloads[path] for path in asset_paths}
        try:
            readme = payloads["README.txt"].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ArchiveIntegrityError("README.txt is not UTF-8") from exc
        return ArchiveContents(root, manifest, project, tuple(visit_records), assets, readme)


def _validate_manifest(manifest: Mapping[str, Any], payloads: Mapping[str, bytes]) -> None:
    files = manifest.get("files")
    assets = manifest.get("assets")
    visits = manifest.get("visits")
    if not isinstance(files, list) or not isinstance(assets, list) or not isinstance(visits, list):
        raise ArchiveIntegrityError("manifest lists are malformed")
    content_paths = set(payloads) - {"archive_manifest.json", "checksums.sha256"}
    manifest_paths: set[str] = set()
    for record in files:
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            raise ArchiveIntegrityError("manifest file record is malformed")
        path = _safe_relative_path(record["path"])
        if path in manifest_paths:
            raise ArchiveIntegrityError(f"duplicate manifest file record: {path}")
        manifest_paths.add(path)
        if path not in payloads or record.get("size") != len(payloads[path]) or record.get("sha256") != _sha256(payloads[path]):
            raise ArchiveIntegrityError(f"manifest file metadata mismatch: {path}")
    if manifest_paths != content_paths:
        raise ArchiveIntegrityError("manifest file list does not match archive contents")

    asset_paths: set[str] = set()
    for record in assets:
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            raise ArchiveIntegrityError("manifest asset record is malformed")
        path = _safe_relative_path(record["path"])
        if path in asset_paths or path not in payloads:
            raise ArchiveIntegrityError(f"invalid manifest asset path: {path}")
        asset_paths.add(path)
        if record.get("size") != len(payloads[path]) or record.get("sha256") != _sha256(payloads[path]):
            raise ArchiveIntegrityError(f"manifest asset metadata mismatch: {path}")

    counts = manifest.get("counts")
    if not isinstance(counts, dict) or counts.get("visits") != len(visits) or counts.get("assets") != len(assets):
        raise ArchiveIntegrityError("manifest counts do not match its records")
    if counts.get("files") != len(files) or counts.get("bytes") != sum(len(payloads[path]) for path in content_paths):
        raise ArchiveIntegrityError("manifest file counts do not match archive contents")


def _record_id(record: Mapping[str, Any], kind: str) -> str:
    value = record.get("id", record.get(f"{kind}_id"))
    if value is None or not str(value).strip():
        raise ArchiveError(f"{kind} record requires an id")
    return str(value)


def _safe_component(value: str, label: str) -> str:
    cleaned = _SAFE_COMPONENT.sub("_", value).strip(" ._")
    if not cleaned:
        raise ArchivePathError(f"{label} is empty after sanitizing")
    return cleaned[:120]


def _safe_relative_path(value: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        raise ArchivePathError(f"unsafe archive path: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ArchivePathError(f"unsafe archive path: {value!r}")
    if ":" in path.parts[0]:
        raise ArchivePathError(f"unsafe archive path: {value!r}")
    normalized = path.as_posix()
    if normalized.endswith("/"):
        raise ArchivePathError(f"unsafe archive path: {value!r}")
    return normalized


def _ensure_unique(entries: Mapping[str, bytes], new_path: str) -> None:
    if any(path.casefold() == new_path.casefold() for path in entries):
        raise ArchivePathError(f"duplicate archive path: {new_path}")


def _read_source(source: bytes | bytearray | memoryview | str | PathLike[str] | BinaryIO) -> bytes:
    if isinstance(source, (bytes, bytearray, memoryview)):
        return bytes(source)
    if isinstance(source, (str, PathLike)):
        return Path(source).read_bytes()
    read = getattr(source, "read", None)
    if not callable(read):
        raise TypeError("asset source must be bytes, a path, or a binary stream")
    position = None
    try:
        position = source.tell()
    except (AttributeError, OSError):
        pass
    payload = read()
    if position is not None:
        try:
            source.seek(position)
        except (AttributeError, OSError):
            pass
    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise TypeError("asset stream must be opened in binary mode")
    return bytes(payload)


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, default=_json_default) + "\n").encode("utf-8")


def _json_default(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


def _load_object(payload: bytes, name: str) -> dict[str, Any]:
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArchiveIntegrityError(f"invalid JSON: {name}") from exc
    if not isinstance(value, dict):
        raise ArchiveIntegrityError(f"JSON record must be an object: {name}")
    return value


def _file_record(path: str, payload: bytes) -> dict[str, Any]:
    return {"path": path, "size": len(payload), "sha256": _sha256(payload)}


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _export_timestamp(value: datetime | str | None) -> str:
    if value is None:
        value = datetime.now(timezone.utc)
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ArchiveError("exported_at must be an ISO timestamp") from exc
    if value.tzinfo is None:
        raise ArchiveError("exported_at must include a timezone")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_checksums(payload: bytes) -> dict[str, str]:
    try:
        lines = payload.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise ArchiveIntegrityError("checksums.sha256 is not UTF-8") from exc
    result: dict[str, str] = {}
    for line in lines:
        if len(line) < 67 or line[64:66] != "  ":
            raise ArchiveIntegrityError("malformed checksum line")
        digest, path = line[:64], line[66:]
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ArchiveIntegrityError("malformed checksum digest")
        path = _safe_relative_path(path)
        if path in result:
            raise ArchiveIntegrityError(f"duplicate checksum path: {path}")
        result[path] = digest
    return result


def _readme() -> str:
    return (
        "SiteScribe complete archive (schema version 1)\n"
        "\n"
        "project.json and each visits/*/visit.json contain the structured records.\n"
        "Visit folders also contain original and generated assets. The manifest records\n"
        "asset metadata independently of EXIF. Verify integrity with checksums.sha256.\n"
    )
