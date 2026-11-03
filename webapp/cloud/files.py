"""Authorized access to private cloud objects."""

from __future__ import annotations

import uuid

from flask import Blueprint, g, jsonify, redirect
from sqlalchemy import select

from webapp.cloud.auth.blueprint import require_cloud_user
from webapp.cloud.db.models import File


def create_files_blueprint(database, auth, store) -> Blueprint:
    blueprint = Blueprint("cloud_files", __name__)

    @blueprint.get("/api/files/<file_id>")
    @require_cloud_user(auth)
    def download(file_id):
        try:
            parsed_id = uuid.UUID(file_id)
        except (TypeError, ValueError):
            return jsonify(error="file not found"), 404
        with database.transaction() as db:
            record = db.scalar(select(File).where(
                File.id == parsed_id,
                File.workspace_id == g.cloud_user.workspace_id,
            ))
            if record is None:
                return jsonify(error="file not found"), 404
            signed = store.signed_url(record.storage_key, expires_in=60)
        response = redirect(signed, code=302)
        response.headers["Cache-Control"] = "private, no-store"
        return response

    return blueprint
