"""Production cloud application factory.

The legacy local application remains available in webapp.server while the
Render service runs this database-backed application.
"""

from __future__ import annotations

import os

from flask import Flask, g, jsonify, render_template, send_from_directory
from sqlalchemy import text

from webapp.cloud.api import create_api_blueprint
from webapp.cloud.admin import create_admin_blueprint
from webapp.cloud.capture import create_capture_blueprint
from webapp.cloud.auth import (
    AuthConfig, AuthenticationService, SupabaseAuthClient, TokenCipher,
    create_auth_blueprint, require_cloud_user,
)
from webapp.cloud.db import create_database
from webapp.cloud.files import create_files_blueprint
from webapp.cloud.exports import create_exports_blueprint
from webapp.cloud.reports import create_reports_blueprint
from webapp.cloud.ops import configure_json_logging, create_health_blueprint
from webapp.cloud.storage import SupabaseBlobStore


def create_app() -> Flask:
    configure_json_logging(os.environ.get("LOG_LEVEL", "INFO"))
    config = AuthConfig.from_env()
    database = create_database()
    auth = AuthenticationService(database, config, TokenCipher.from_env())
    auth_client = SupabaseAuthClient(config)
    blob_store = SupabaseBlobStore(
        supabase_url=config.supabase_url,
        secret_key=os.environ["SUPABASE_SECRET_KEY"],
        bucket=os.environ.get("SUPABASE_STORAGE_BUCKET", "project-files"),
    )

    app = Flask(__name__)
    app.secret_key = os.environ["FLASK_SECRET_KEY"]
    app.config.update(
        SESSION_COOKIE_SECURE=config.cookie_secure,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        MAX_CONTENT_LENGTH=50 * 1024 * 1024,
    )

    def ready_check():
        with database.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True, {"database": "ok", "auth": "configured", "storage": "configured"}

    app.register_blueprint(create_health_blueprint(ready_check))
    app.register_blueprint(create_auth_blueprint(auth_client, auth))
    app.register_blueprint(create_api_blueprint(database, auth))
    app.register_blueprint(create_admin_blueprint(auth, blob_store))
    app.register_blueprint(create_capture_blueprint(database, auth, blob_store))
    app.register_blueprint(create_files_blueprint(database, auth, blob_store))
    app.register_blueprint(create_exports_blueprint(database, auth, blob_store))
    app.register_blueprint(create_reports_blueprint(database, auth, blob_store))

    @app.get("/")
    @require_cloud_user(auth, redirect_to_login=True)
    def dashboard():
        return render_template("cloud_dashboard.html", user=g.cloud_user)

    @app.get("/visits/<visit_id>")
    @require_cloud_user(auth, redirect_to_login=True)
    def capture_visit(visit_id):
        return render_template("cloud_visit.html", visit_id=visit_id, user=g.cloud_user)

    @app.get("/visits/<visit_id>/overview")
    @require_cloud_user(auth, redirect_to_login=True)
    def visit_overview(visit_id):
        return render_template("cloud_visit_overview.html", visit_id=visit_id, user=g.cloud_user)

    @app.get("/service-worker.js")
    def service_worker():
        response = send_from_directory(
            app.static_folder, "service-worker.js", mimetype="application/javascript"
        )
        response.headers["Cache-Control"] = "no-cache"
        response.headers["Service-Worker-Allowed"] = "/"
        return response

    @app.errorhandler(413)
    def too_large(_exc):
        return jsonify(error="upload exceeds the 50 MiB request limit"), 413

    return app


app = create_app()
