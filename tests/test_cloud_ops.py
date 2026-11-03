import json
import logging

from flask import Flask

from webapp.cloud.ops.health import create_health_blueprint
from webapp.cloud.ops.logging import JsonFormatter


def app_with(check=None):
    app = Flask(__name__)
    app.register_blueprint(create_health_blueprint(check))
    return app


def test_liveness_does_not_depend_on_external_services():
    response = app_with().test_client().get("/health/live")
    assert response.status_code == 200
    assert response.json["status"] == "ok"


def test_readiness_reports_dependency_state():
    response = app_with(lambda: (True, {"database": "ok", "storage": "ok"})).test_client().get(
        "/health/ready"
    )
    assert response.status_code == 200
    assert response.json["checks"]["database"] == "ok"


def test_readiness_fails_closed_without_leaking_exception():
    def broken():
        raise RuntimeError("credential must not leak")

    response = app_with(broken).test_client().get("/health/ready")
    assert response.status_code == 503
    assert "credential" not in response.get_data(as_text=True)


def test_json_formatter_produces_machine_readable_log():
    record = logging.LogRecord("sitescribe", logging.INFO, "", 0, "ready", (), None)
    value = json.loads(JsonFormatter().format(record))
    assert value["message"] == "ready"
    assert value["level"] == "INFO"
