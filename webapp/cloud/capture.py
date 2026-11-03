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
            items = list(db.scalars(_items_query(visit.id)))
            return jsonify([_item_json(item) for item in items])

    @api.get("/api/visits/<visit_id>/overview")
    @guarded
    def visit_overview(visit_id):
        with database.transaction() as db:
            visit = _visit(db, visit_id)
            project = db.get(Project, visit.project_id)
            items = list(db.scalars(_items_query(visit.id)))
            observations = [value for item in items for value in item.observations]
            return jsonify({
                "project": {"id": str(project.id), "name": project.name},
                "visit": {"id": str(visit.id), "visit_date": visit.visit_date.isoformat()},
                "stats": {
                    "items": len(items),
                    "included": sum(value.include_in_report for value in observations),
                    "critical": sum(
                        str(value.severity or "").lower() == "critical"
                        for value in observations
                    ),
                },
                "items": [_item_json(item) for item in items],
            })

    @api.post("/api/visits/<visit_id>/items")
    @guarded
    def create_item(visit_id):
        body = request.get_json(silent=True) or {}
        item_id, error = _client_id(body.get("id"))
        if error:
            return error
        observation_id, error = _client_id(body.get("observation_id"))
        if error:
            return error
        with database.transaction() as db:
            visit = _visit(db, visit_id)
            if item_id is not None:
                existing = db.get(Item, item_id)
                if existing is not None:
                    # Offline replay: the phone generated this ID, so a second
                    # request with it is the same item, not a new one.
                    if existing.visit_id != visit.id:
                        return jsonify(error="item id already in use"), 409
                    return jsonify(_item_json(existing)), 200
            if observation_id is not None and db.get(Observation, observation_id):
                return jsonify(error="observation id already in use"), 409
            last = db.execute(select(
                func.coalesce(func.max(Item.number), 0),
                func.coalesce(func.max(Item.position), 0),
            ).where(Item.visit_id == visit.id)).one()
            item = Item(visit_id=visit.id, number=last[0] + 1, position=last[1] + 1)
            if item_id is not None:
                item.id = item_id
            db.add(item)
            db.flush()
            if body.get("create_observation") or observation_id is not None:
                first = Observation(item_id=item.id, sequence=1, description="")
                if observation_id is not None:
                    first.id = observation_id
                db.add(first)
                db.flush()
            return jsonify(_item_json(item)), 201

    @api.delete("/api/visits/<visit_id>/items/<item_id>")
    @guarded
    def delete_item(visit_id, item_id):
        storage_keys = []
        with database.transaction() as db:
            visit = _visit(db, visit_id)
            item = db.scalar(select(Item).where(
                Item.id == _uuid(item_id), Item.visit_id == visit.id
            ))
            if item is None:
                return jsonify(error="item not found"), 404
            records = list(db.scalars(
                select(File).join(ObservationFile).join(Observation).where(
                    Observation.item_id == item.id
                )
            ))
            storage_keys = [record.storage_key for record in records]
            for record in records:
                db.delete(record)
            db.delete(item)
        for key in storage_keys:
            store.delete(key)
        return "", 204

    @api.post("/api/visits/<visit_id>/items/<item_id>/observations")
    @guarded
    def create_observation(visit_id, item_id):
        body = request.get_json(silent=True) or {}
        observation_id, error = _client_id(body.get("id"))
        if error:
            return error
        with database.transaction() as db:
            visit = _visit(db, visit_id)
            item = db.scalar(select(Item).where(
                Item.id == _uuid(item_id), Item.visit_id == visit.id
            ))
            if item is None:
                return jsonify(error="item not found"), 404
            if observation_id is not None:
                existing = db.get(Observation, observation_id)
                if existing is not None:
                    if existing.item_id != item.id:
                        return jsonify(error="observation id already in use"), 409
                    return jsonify(_observation_json(existing)), 200
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
            if observation_id is not None:
                observation.id = observation_id
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
        digest = hashlib.sha256(payload).hexdigest()
        kind = request.form.get("kind", "photo")
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
                for link in observation.file_links:
                    # Offline replay: the first attempt reached the server but
                    # its response was lost. Return the stored file instead of
                    # attaching a second copy.
                    if link.file.sha256 == digest and link.file.kind == kind:
                        return jsonify(_file_json(link.file)), 200
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
                    kind=kind,
                    storage_key=uploaded_key, mime_type=metadata.content_type,
                    size_bytes=metadata.size,
                    sha256=digest,
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
                result = _file_json(record)
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


def _client_id(value):
    """Parse an optional phone-generated UUID. Returns (uuid | None, error)."""
    if value in (None, ""):
        return None, None
    parsed = _uuid(str(value))
    if parsed is None:
        return None, (jsonify(error="id must be a UUID"), 400)
    return parsed, None


def _file_json(record):
    return {
        "id": str(record.id), "kind": record.kind,
        "filename": record.original_filename,
        "mime_type": record.mime_type, "size": record.size_bytes,
        "download_url": f"/api/files/{record.id}",
    }


def _uuid(value):
    try:
        return uuid.UUID(value)
    except (TypeError, ValueError):
        return None


def _items_query(visit_id):
    return (
        select(Item)
        .options(
            selectinload(Item.observations)
            .selectinload(Observation.file_links)
            .selectinload(ObservationFile.file)
        )
        .where(Item.visit_id == visit_id)
        .order_by(Item.position, Item.id)
    )


def _item_json(item):
    return {
        "id": str(item.id), "number": item.number, "position": item.position,
        "observations": [
            _observation_json(value)
            for value in sorted(item.observations, key=lambda row: (row.sequence, row.id))
        ],
    }


def _observation_json(value):
    return {
        "id": str(value.id), "item_id": str(value.item_id),
        "sequence": value.sequence, "description": value.description,
        "caption": value.caption, "severity": value.severity, "tags": value.tags,
        "action": value.action, "include_in_report": value.include_in_report,
        "plan_page": value.plan_page, "plan_x": value.plan_x, "plan_y": value.plan_y,
        "files": [{
            "id": str(link.file.id), "kind": link.file.kind,
            "media_role": link.media_role, "filename": link.file.original_filename,
            "mime_type": link.file.mime_type,
            "download_url": f"/api/files/{link.file.id}",
        } for link in sorted(value.file_links, key=lambda row: row.position)],
    }
