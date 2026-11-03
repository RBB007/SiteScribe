"""Liveness and dependency-aware readiness endpoints."""

from collections.abc import Callable

from flask import Blueprint, jsonify


ReadyCheck = Callable[[], tuple[bool, dict]]


def create_health_blueprint(ready_check: ReadyCheck | None = None) -> Blueprint:
    blueprint = Blueprint("cloud_health", __name__)

    @blueprint.get("/health/live")
    def live():
        return jsonify(status="ok", service="sitescribe")

    @blueprint.get("/health/ready")
    def ready():
        if ready_check is None:
            return jsonify(status="not_ready", checks={}), 503
        try:
            healthy, checks = ready_check()
        except Exception:
            healthy, checks = False, {"dependencies": "unavailable"}
        status = 200 if healthy else 503
        return jsonify(
            status="ready" if healthy else "not_ready",
            checks=checks,
        ), status

    return blueprint
