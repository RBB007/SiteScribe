"""Authenticated HTTP endpoint for AI-assisted report delivery."""
from __future__ import annotations

import uuid

from flask import Blueprint, current_app, g, jsonify
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from webapp.cloud.auth.blueprint import require_cloud_user
from webapp.cloud.db.models import Item, Observation, ObservationFile, Project, Visit
from webapp.cloud.exports import _build
from webapp.cloud.report_delivery import email_report
from webapp.cloud.report_service import generate, records


def create_reports_blueprint(database, auth, store):
    blueprint = Blueprint("cloud_reports", __name__)

    @blueprint.post("/api/visits/<visit_id>/exports/report")
    @require_cloud_user(auth)
    def generate_report(visit_id):
        try:
            parsed = uuid.UUID(visit_id)
        except (TypeError, ValueError):
            parsed = None
        with database.transaction() as db:
            visit = db.scalar(select(Visit).join(Project).where(
                Visit.id == parsed, Project.workspace_id == g.cloud_user.workspace_id
            ))
            if visit is None:
                return jsonify(error="visit not found"), 404
            project = db.get(Project, visit.project_id)
            items = list(db.scalars(select(Item).options(
                selectinload(Item.observations).selectinload(Observation.file_links)
                .selectinload(ObservationFile.file)
            ).where(Item.visit_id == visit.id).order_by(Item.position, Item.id)))
            raw_zip = _build(db, store, project, [visit], "visit")
            observation_rows, photo_files = records(items)
        try:
            links = generate(
                database, store, g.cloud_user, project, visit,
                observation_rows, photo_files, raw_zip,
            )
            try:
                emailed = email_report(g.cloud_user.email, project.name, links)
            except Exception:
                current_app.logger.exception("report email delivery failed")
                emailed = False
            return jsonify({
                "links": links, "emailed": emailed,
                "message": "Report generated and email sent." if emailed else
                           "Report generated. Email delivery is not configured.",
            })
        except RuntimeError as error:
            return jsonify(error=str(error)), 503
        except Exception:
            current_app.logger.exception("report generation failed")
            return jsonify(error="Report generation failed. Your captured data is safe."), 502

    return blueprint
