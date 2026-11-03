"""Workspace-scoped project and visit JSON API."""

from __future__ import annotations

import uuid
from datetime import date

from flask import Blueprint, g, jsonify, request

from webapp.cloud.auth.blueprint import require_cloud_user
from webapp.cloud.db.repositories import (
    AdminRequired, ArchivedResource, MembershipRequired, ProjectRepository,
    ResourceNotFound, VisitRepository, require_admin,
)
from webapp.cloud.db.models import MemberRole, MemberStatus, Profile, WorkspaceMember
from sqlalchemy import select


def create_api_blueprint(database, auth) -> Blueprint:
    api = Blueprint("cloud_api", __name__)
    guarded = require_cloud_user(auth)

    def repos(db):
        user = g.cloud_user
        return (
            ProjectRepository(db, user.workspace_id, user.profile_id),
            VisitRepository(db, user.workspace_id, user.profile_id),
        )

    @api.get("/api/projects")
    @guarded
    def list_projects():
        with database.transaction() as db:
            projects, _ = repos(db)
            values = projects.list(archived=request.args.get("archived") == "true")
            return jsonify([_project_json(value) for value in values])

    @api.post("/api/projects")
    @guarded
    def create_project():
        body = request.get_json(silent=True) or {}
        with database.transaction() as db:
            projects, _ = repos(db)
            value = projects.create(
                body.get("name", ""), project_number=body.get("project_number"),
                address=body.get("address"), client=body.get("client"),
            )
            return jsonify(_project_json(value)), 201

    @api.get("/api/projects/<project_id>")
    @guarded
    def get_project(project_id):
        with database.transaction() as db:
            projects, _ = repos(db)
            return jsonify(_project_json(projects.get(_uuid(project_id))))

    @api.patch("/api/projects/<project_id>")
    @guarded
    def update_project(project_id):
        body = request.get_json(silent=True) or {}
        with database.transaction() as db:
            projects, _ = repos(db)
            value = projects.get(_uuid(project_id))
            for field in ("name", "project_number", "address", "client"):
                if field in body:
                    setattr(value, field, _text(body[field], required=field == "name"))
            return jsonify(_project_json(value))

    @api.delete("/api/projects/<project_id>")
    @guarded
    def archive_project(project_id):
        with database.transaction() as db:
            projects, _ = repos(db)
            return jsonify(_project_json(projects.archive(_uuid(project_id))))

    @api.post("/api/projects/<project_id>/restore")
    @guarded
    def restore_project(project_id):
        with database.transaction() as db:
            projects, _ = repos(db)
            return jsonify(_project_json(projects.restore(_uuid(project_id))))

    @api.get("/api/projects/<project_id>/visits")
    @guarded
    def list_visits(project_id):
        with database.transaction() as db:
            _, visits = repos(db)
            values = visits.list(
                _uuid(project_id), archived=request.args.get("archived") == "true"
            )
            return jsonify([_visit_json(value) for value in values])

    @api.post("/api/projects/<project_id>/visits")
    @guarded
    def create_visit(project_id):
        body = request.get_json(silent=True) or {}
        try:
            visit_date = date.fromisoformat(str(body.get("visit_date", "")))
        except ValueError as exc:
            raise ValueError("visit_date must be an ISO date") from exc
        fields = (
            "report_number", "engineer", "visit_time", "conditions",
            "attendees", "summary", "report_options",
        )
        values = {key: body[key] for key in fields if key in body}
        with database.transaction() as db:
            _, visits = repos(db)
            value = visits.create(_uuid(project_id), visit_date, **values)
            return jsonify(_visit_json(value)), 201

    @api.get("/api/projects/<project_id>/visits/<visit_id>")
    @guarded
    def get_visit(project_id, visit_id):
        with database.transaction() as db:
            _, visits = repos(db)
            return jsonify(_visit_json(visits.get(_uuid(project_id), _uuid(visit_id))))

    @api.patch("/api/projects/<project_id>/visits/<visit_id>")
    @guarded
    def update_visit(project_id, visit_id):
        body = request.get_json(silent=True) or {}
        with database.transaction() as db:
            _, visits = repos(db)
            value = visits.get(_uuid(project_id), _uuid(visit_id))
            if "visit_date" in body:
                value.visit_date = date.fromisoformat(str(body["visit_date"]))
            fields = (
                "report_number", "engineer", "visit_time", "conditions",
                "attendees", "summary", "report_options",
            )
            for field in fields:
                if field in body:
                    setattr(value, field, body[field])
            return jsonify(_visit_json(value))

    @api.delete("/api/projects/<project_id>/visits/<visit_id>")
    @guarded
    def archive_visit(project_id, visit_id):
        with database.transaction() as db:
            _, visits = repos(db)
            value = visits.archive(_uuid(project_id), _uuid(visit_id))
            return jsonify(_visit_json(value))

    @api.post("/api/projects/<project_id>/visits/<visit_id>/restore")
    @guarded
    def restore_visit(project_id, visit_id):
        with database.transaction() as db:
            _, visits = repos(db)
            value = visits.restore(_uuid(project_id), _uuid(visit_id))
            return jsonify(_visit_json(value))

    @api.get("/api/members")
    @guarded
    def list_members():
        with database.transaction() as db:
            require_admin(db, g.cloud_user.workspace_id, g.cloud_user.profile_id)
            rows = db.execute(
                select(WorkspaceMember, Profile)
                .join(Profile, WorkspaceMember.profile_id == Profile.id)
                .where(WorkspaceMember.workspace_id == g.cloud_user.workspace_id)
                .order_by(Profile.email)
            )
            return jsonify([{
                "id": str(member.id), "profile_id": str(profile.id),
                "email": profile.email, "role": member.role.value,
                "status": member.status.value,
            } for member, profile in rows])

    @api.patch("/api/members/<member_id>")
    @guarded
    def update_member(member_id):
        body = request.get_json(silent=True) or {}
        with database.transaction() as db:
            require_admin(db, g.cloud_user.workspace_id, g.cloud_user.profile_id)
            member = db.scalar(select(WorkspaceMember).where(
                WorkspaceMember.id == _uuid(member_id),
                WorkspaceMember.workspace_id == g.cloud_user.workspace_id,
            ))
            if member is None:
                raise ResourceNotFound("member not found")
            if "role" in body:
                member.role = MemberRole(body["role"])
            if "status" in body:
                member.status = MemberStatus(body["status"])
            return jsonify({
                "id": str(member.id), "profile_id": str(member.profile_id),
                "role": member.role.value, "status": member.status.value,
            })

    @api.errorhandler(ResourceNotFound)
    def not_found(exc):
        return jsonify(error=str(exc)), 404

    @api.errorhandler(MembershipRequired)
    @api.errorhandler(ArchivedResource)
    @api.errorhandler(AdminRequired)
    def forbidden(exc):
        return jsonify(error=str(exc)), 403

    @api.errorhandler(ValueError)
    def invalid(exc):
        return jsonify(error=str(exc)), 400

    return api


def _uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except (ValueError, TypeError) as exc:
        raise ResourceNotFound("resource not found") from exc


def _text(value, *, required=False):
    result = str(value or "").strip()
    if required and not result:
        raise ValueError("name is required")
    return result or None


def _project_json(value):
    return {
        "id": str(value.id),
        "name": value.name,
        "project_number": value.project_number,
        "address": value.address,
        "client": value.client,
        "created_at": value.created_at.isoformat(),
        "updated_at": value.updated_at.isoformat(),
        "archived_at": value.archived_at.isoformat() if value.archived_at else None,
        "purge_after": value.purge_after.isoformat() if value.purge_after else None,
    }


def _visit_json(value):
    return {
        "id": str(value.id),
        "project_id": str(value.project_id),
        "visit_date": value.visit_date.isoformat(),
        "report_number": value.report_number,
        "engineer": value.engineer,
        "visit_time": value.visit_time,
        "conditions": value.conditions,
        "attendees": value.attendees,
        "summary": value.summary,
        "report_options": value.report_options,
        "created_at": value.created_at.isoformat(),
        "updated_at": value.updated_at.isoformat(),
        "archived_at": value.archived_at.isoformat() if value.archived_at else None,
        "purge_after": value.purge_after.isoformat() if value.purge_after else None,
    }
