"""Explicit visit-scoped field capture API."""

from __future__ import annotations

import hashlib
import uuid

from flask import Blueprint, g, jsonify, request
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from webapp.cloud.auth.blueprint import require_cloud_user
from webapp.cloud.db.models import File, Item, Observation, ObservationFile, Project, Visit
from webapp.cloud.storage import build_private_key, validate_upload


def create_capture_blueprint(database, auth, store) -> Blueprint:
    api = Blueprint("cloud_capture", __name__)
    guarded = require_cloud_user(auth)

    @api.get("/api/visits/<visit_id>/items")
    @guarded
    def list_items(visit_id):
        with database.transaction() as db:
            visit = _visit(db, visit_id)
            items = list(db.scalars(
                select(Item).options(selectinload(Item.observations))
                .where(Item.visit_id == visit.id).order_by(Item.position, Item.id)
            ))
            return jsonify([_item_json(item) for item in items])

    @api.post("/api/visits/<visit_id>/items")
    @guarded
    def create_item(visit_id):
        with database.transaction() as db:
            visit = _visit(db, visit_id)
            last = db.execute(select(
                func.coalesce(func.max(Item.number), 0),
                func.coalesce(func.max(Item.position), 0),
            ).where(Item.visit_id == visit.id)).one()
            item = Item(visit_id=visit.id, number=last[0] + 1, position=last[1] + 1)
            db.add(item)
            db.flush()
            return jsonify(_item_json(item)), 201

    @api.post("/api/visits/<visit_id>/items/<item_id>/observations")
    @guarded
    def create_observation(visit_id, item_id):
        body = request.get_json(silent=True) or {}
        with database.transaction() as db:
            visit = _visit(db, visit_id)
            item = db.scalar(select(Item).where(
                Item.id == _uuid(item_id), Item.visit_id == visit.id
            ))
            if item is None:
                return jsonify(error="item not found"), 404
            sequence = db.scalar(select(func.coalesce(func.max(Observation.sequence), 0))
                                 .where(Observation.item_id == item.id)) + 1
            observation = Observation(
                item_id=item.id, sequence=sequence,
                description=str(body.get("description") or ""),
                caption=body.get("caption"), severity=body.get("severity"),
                tags=body.get("tags") or [], action=body.get("action"),
                include_in_report=body.get("include_in_report", True),
                plan_page=body.get("plan_page"), plan_x=body.get("plan_x"),
                plan_y=body.get("plan_y"),
            )
            db.add(observation)
            db.flush()
            return jsonify(_observation_json(observation)), 201

    @api.patch("/api/visits/<visit_id>/observations/<observation_id>")
    @guarded
    def update_observation(visit_id, observation_id):
        body = request.get_json(silent=True) or {}
        with database.transaction() as db:
            visit = _visit(db, visit_id)
            observation = db.scalar(
                select(Observation).join(Item).where(
                    Observation.id == _uuid(observation_id), Item.visit_id == visit.id
                )
            )
            if observation is None:
                return jsonify(error="observation not found"), 404
            fields = (
                "description", "caption", "severity", "tags", "action",
                "include_in_report", "plan_page", "plan_x", "plan_y",
            )
            for field in fields:
                if field in body:
                    setattr(observation, field, body[field])
            return jsonify(_observation_json(observation))

    @api.post("/api/visits/<visit_id>/observations/<observation_id>/files")
    @guarded
    def upload_file(visit_id, observation_id):
        incoming = request.files.get("file")
        if incoming is None:
            return jsonify(error="file is required"), 400
        payload = incoming.read()
        metadata = validate_upload(
            filename=incoming.filename or "",
            content_type=incoming.mimetype or "",
            size=len(payload),
        )
        file_id = uuid.uuid4()
        uploaded_key = None
        try:
            with database.transaction() as db:
                visit = _visit(db, visit_id)
                observation = db.scalar(
                    select(Observation).join(Item).where(
                        Observation.id == _uuid(observation_id), Item.visit_id == visit.id
                    )
                )
                if observation is None:
                    return jsonify(error="observation not found"), 404
                uploaded_key = build_private_key(
                    workspace_id=g.cloud_user.workspace_id,
                    project_id=visit.project_id,
                    visit_id=visit.id,
                    file_id=file_id,
                    filename=metadata.filename,
                )
                store.put(uploaded_key, payload, content_type=metadata.content_type)
                record = File(
                    id=file_id, workspace_id=g.cloud_user.workspace_id,
                    project_id=visit.project_id, visit_id=visit.id,
                    kind=request.form.get("kind", "photo"),
                    storage_key=uploaded_key, mime_type=metadata.content_type,
                    size_bytes=metadata.size,
                    sha256=hashlib.sha256(payload).hexdigest(),
                    original_filename=metadata.filename,
                    created_by_id=g.cloud_user.profile_id,
                )
                db.add(record)
                db.add(ObservationFile(
                    observation_id=observation.id, file_id=record.id,
                    media_role=request.form.get("media_role", record.kind),
                    position=len(observation.file_links),
                ))
                db.flush()
                result = {
                    "id": str(record.id), "kind": record.kind,
                    "filename": record.original_filename,
                    "mime_type": record.mime_type, "size": record.size_bytes,
                    "download_url": f"/api/files/{record.id}",
                }
            return jsonify(result), 201
        except Exception:
            if uploaded_key is not None:
                store.delete(uploaded_key)
            raise

    return api


def _visit(db, value):
    visit_id = _uuid(value)
    visit = db.scalar(select(Visit).join(Project).where(
        Visit.id == visit_id,
        Visit.archived_at.is_(None),
        Project.workspace_id == g.cloud_user.workspace_id,
        Project.archived_at.is_(None),
    ))
    if visit is None:
        from werkzeug.exceptions import NotFound
        raise NotFound("visit not found")
    return visit


def _uuid(value):
    try:
        return uuid.UUID(value)
    except (TypeError, ValueError):
        return None


def _item_json(item):
    return {
        "id": str(item.id), "number": item.number, "position": item.position,
        "observations": [_observation_json(value) for value in item.observations],
    }


def _observation_json(value):
    return {
        "id": str(value.id), "item_id": str(value.item_id),
        "sequence": value.sequence, "description": value.description,
        "caption": value.caption, "severity": value.severity, "tags": value.tags,
        "action": value.action, "include_in_report": value.include_in_report,
        "plan_page": value.plan_page, "plan_x": value.plan_x, "plan_y": value.plan_y,
    }
