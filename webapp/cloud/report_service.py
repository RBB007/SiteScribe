"""Generate and retain the three visit deliverables."""
from __future__ import annotations

import hashlib
import tempfile
import uuid
from pathlib import Path

from webapp.cloud.admin import download_template, load_secret, load_text
from webapp.cloud.db.models import File
from webapp.cloud.report_agent import draft_report
from webapp.cloud.report_output import create_outputs
from webapp.cloud.storage import sanitize_filename


def generate(database, store, user, project, visit, observations, photo_files, raw_zip):
    project_data = {"name": project.name, "address": project.address,
                    "project_number": project.project_number, "client": project.client}
    visit_data = {"visit_date": visit.visit_date, "engineer": visit.engineer,
                  "report_number": visit.report_number, "conditions": visit.conditions,
                  "visit_time": visit.visit_time, "report_options": visit.report_options}
    project_id, visit_id = project.id, visit.id
    uploaded = []
    try:
        with tempfile.TemporaryDirectory(prefix="sitescribe-report-") as folder:
            root = Path(folder); photo_paths = {}; evidence = []
            for row in photo_files:
                destination = root / (row["id"] + Path(row["filename"]).suffix)
                store.download_to(row["storage_key"], destination)
                photo_paths.setdefault(row["observation_id"], []).append(destination)
                evidence.append((row["observation_id"], destination, row["mime_type"]))
            api_key = load_secret(store, user.workspace_id)
            instructions = load_text(store, user.workspace_id)
            template = download_template(store, user.workspace_id, root / "report_template.docx")
            drafted = draft_report(
                project_data, visit_data, observations, evidence, api_key, instructions
            )
            docx, pdf = create_outputs(
                project_data, visit_data, observations, drafted, photo_paths, root, template
            )
            outputs = [
                ("Word report", docx.name, "application/vnd.openxmlformats-officedocument.wordprocessingml.document", docx.read_bytes()),
                ("PDF report", pdf.name, "application/pdf", pdf.read_bytes()),
                ("complete raw-data ZIP", sanitize_filename(project.name) + "_complete.zip", "application/zip", raw_zip),
            ]
            stored = []
            prefix = f"{user.workspace_id}/{project_id}/{visit_id}/reports"
            for label, filename, mime, payload in outputs:
                key = f"{prefix}/{uuid.uuid4()}-{sanitize_filename(filename)}"
                store.put(key, payload, content_type=mime); uploaded.append(key)
                stored.append((label, filename, mime, payload, key))
            with database.transaction() as db:
                for _label, filename, mime, payload, key in stored:
                    db.add(File(
                        workspace_id=user.workspace_id, project_id=project_id, visit_id=visit_id,
                        kind="report" if mime != "application/zip" else "archive",
                        storage_key=key, mime_type=mime, size_bytes=len(payload),
                        sha256=hashlib.sha256(payload).hexdigest(), original_filename=filename,
                        created_by_id=user.profile_id,
                    ))
            return {label: store.signed_url(key, expires_in=604800)
                    for label, _filename, _mime, _payload, key in stored}
    except Exception:
        for key in uploaded:
            store.delete(key)
        raise


def records(items):
    observations, photos = [], []
    for item in items:
        for row in sorted(item.observations, key=lambda value: value.sequence):
            observations.append({
                "id": str(row.id), "number": item.number, "description": row.description,
                "caption": row.caption, "severity": row.severity or "Low", "tags": row.tags,
                "action": row.action, "include_in_report": row.include_in_report,
            })
            for link in sorted(row.file_links, key=lambda value: value.position):
                if link.file.kind == "photo":
                    photos.append({"id": str(link.file.id), "observation_id": str(row.id),
                                   "filename": link.file.original_filename,
                                   "mime_type": link.file.mime_type,
                                   "storage_key": link.file.storage_key})
    return observations, photos
