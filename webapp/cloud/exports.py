"""Complete, checksum-verified raw archive HTTP exports."""

from __future__ import annotations

import io
import tempfile
import uuid
from pathlib import Path

from flask import Blueprint, g, jsonify, send_file
from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from webapp.cloud.archive import ArchiveAsset, build_archive
from webapp.cloud.auth.blueprint import require_cloud_user
from webapp.cloud.db.models import File, Item, ObservationFile, Plan, Project, Visit
from webapp.cloud.storage import sanitize_filename


def create_exports_blueprint(database, auth, store) -> Blueprint:
    blueprint = Blueprint("cloud_exports", __name__)

    @blueprint.post("/api/visits/<visit_id>/exports/archive")
    @require_cloud_user(auth)
    def visit_archive(visit_id):
        parsed = _uuid(visit_id)
        with database.transaction() as db:
            visit = db.scalar(
                select(Visit).join(Project).where(
                    Visit.id == parsed, Project.workspace_id == g.cloud_user.workspace_id
                )
            )
            if visit is None:
                return jsonify(error="visit not found"), 404
            project = db.get(Project, visit.project_id)
            payload = _build(db, store, project, [visit], "visit")
        return _zip(payload, f"{sanitize_filename(project.name)}_{visit.visit_date}.zip")

    @blueprint.post("/api/projects/<project_id>/exports/archive")
    @require_cloud_user(auth)
    def project_archive(project_id):
        parsed = _uuid(project_id)
        with database.transaction() as db:
            project = db.scalar(select(Project).where(
                Project.id == parsed, Project.workspace_id == g.cloud_user.workspace_id
            ))
            if project is None:
                return jsonify(error="project not found"), 404
            visits = list(db.scalars(
                select(Visit).where(Visit.project_id == project.id)
                .order_by(Visit.visit_date, Visit.created_at, Visit.id)
            ))
            payload = _build(db, store, project, visits, "project")
        return _zip(payload, f"{sanitize_filename(project.name)}_complete.zip")

    return blueprint


def _build(db, store, project, visits, kind):
    visit_ids = [visit.id for visit in visits]
    structured = [_visit_record(db, visit) for visit in visits]
    files = list(db.scalars(
        select(File)
        .options(
            selectinload(File.observation_links)
            .selectinload(ObservationFile.observation)
        )
        .where(
            File.project_id == project.id,
            or_(File.visit_id.in_(visit_ids), File.visit_id.is_(None)) if visit_ids else False,
        )
    ))
    with tempfile.TemporaryDirectory(prefix="sitescribe-export-") as directory:
        assets = []
        for record in files:
            local = Path(directory) / str(record.id)
            store.download_to(record.storage_key, local)
            included = _included(record)
            assets.append(ArchiveAsset(
                visit_id=str(record.visit_id or visits[0].id),
                relative_path=_asset_path(record, included),
                source=local,
                kind=record.kind,
                included=included,
                original_filename=record.original_filename,
                mime_type=record.mime_type,
                storage_id=str(record.id),
            ))
        return build_archive(
            _project_record(project), structured, assets,
            app_version="cloud-v1", archive_kind=kind,
        )


def _project_record(project):
    return {
        "id": str(project.id),
        "name": project.name,
        "project_number": project.project_number,
        "address": project.address,
        "client": project.client,
        "created_at": project.created_at,
        "updated_at": project.updated_at,
        "archived_at": project.archived_at,
        "purge_after": project.purge_after,
    }


def _visit_record(db, visit):
    items = list(db.scalars(
        select(Item).options(selectinload(Item.observations))
        .where(Item.visit_id == visit.id).order_by(Item.position, Item.id)
    ))
    plans = list(db.scalars(select(Plan).where(Plan.visit_id == visit.id).order_by(Plan.id)))
    return {
        "id": str(visit.id),
        "project_id": str(visit.project_id),
        "visit_date": visit.visit_date,
        "report_number": visit.report_number,
        "engineer": visit.engineer,
        "visit_time": visit.visit_time,
        "conditions": visit.conditions,
        "attendees": visit.attendees,
        "summary": visit.summary,
        "report_options": visit.report_options,
        "created_at": visit.created_at,
        "updated_at": visit.updated_at,
        "items": [{
            "id": str(item.id),
            "number": item.number,
            "position": item.position,
            "observations": [{
                "id": str(observation.id),
                "sequence": observation.sequence,
                "description": observation.description,
                "caption": observation.caption,
                "severity": observation.severity,
                "tags": observation.tags,
                "action": observation.action,
                "include_in_report": observation.include_in_report,
                "plan_page": observation.plan_page,
                "plan_x": observation.plan_x,
                "plan_y": observation.plan_y,
            } for observation in item.observations],
        } for item in items],
        "plans": [{
            "id": str(plan.id), "file_id": str(plan.file_id),
            "page_count": plan.page_count, "metadata": plan.plan_metadata,
        } for plan in plans],
    }


def _included(record):
    values = {
        link.observation.include_in_report
        for link in record.observation_links
        if link.observation is not None
    }
    return None if not values else any(values)


def _asset_path(record, included):
    category = {
        "photo": "photos/originals/included" if included is not False
                 else "photos/originals/excluded",
        "audio": "audio",
        "plan": "plans/original",
        "marked_plan": "plans/marked",
        "template": "templates",
        "report": "reports",
    }.get(record.kind, f"raw/{sanitize_filename(record.kind)}")
    filename = sanitize_filename(record.original_filename)
    return f"{category}/{record.id}_{filename}"


def _uuid(value):
    try:
        return uuid.UUID(value)
    except (TypeError, ValueError):
        return None


def _zip(payload, filename):
    return send_file(
        io.BytesIO(payload),
        mimetype="application/zip",
        as_attachment=True,
        download_name=filename,
        max_age=0,
    )
