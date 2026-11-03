"""Workspace-admin configuration stored encrypted/private in Supabase."""
from __future__ import annotations

import base64
import hashlib
import os
import tempfile
from functools import wraps
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from flask import Blueprint, g, jsonify, render_template, request

from webapp.cloud.auth.blueprint import require_cloud_user
from webapp.cloud.storage import BlobNotFoundError


NAMES = {"agents": "AGENTS.md", "template": "report_template.docx", "secret": "claude_api_key.enc"}


def create_admin_blueprint(auth, store):
    blueprint = Blueprint("cloud_admin", __name__)

    def admin_only(*, redirect_to_login):
        def decorate(view):
            @wraps(view)
            @require_cloud_user(auth, redirect_to_login=redirect_to_login)
            def wrapped(*args, **kwargs):
                if g.cloud_user.role != "admin":
                    return jsonify(error="administrator access required"), 403
                return view(*args, **kwargs)
            return wrapped
        return decorate

    @blueprint.get("/admin")
    @admin_only(redirect_to_login=True)
    def page():
        return render_template("cloud_admin.html", user=g.cloud_user)

    @blueprint.get("/api/admin/settings")
    @admin_only(redirect_to_login=False)
    def status():
        return jsonify({name: _exists(store, _key(g.cloud_user.workspace_id, filename))
                        for name, filename in NAMES.items()})

    @blueprint.post("/api/admin/settings")
    @admin_only(redirect_to_login=False)
    def update():
        changed = []
        api_key = request.form.get("api_key", "").strip()
        if api_key:
            encrypted = _cipher().encrypt(api_key.encode())
            store.put(_key(g.cloud_user.workspace_id, NAMES["secret"]), encrypted,
                      content_type="application/octet-stream", overwrite=True)
            changed.append("Claude API key")
        agents = request.files.get("agents")
        if agents and agents.filename:
            if Path(agents.filename).name.lower() != "agents.md":
                return jsonify(error="Instructions file must be named AGENTS.md"), 400
            store.put(_key(g.cloud_user.workspace_id, NAMES["agents"]), agents.stream,
                      content_type="text/markdown", overwrite=True)
            changed.append("AGENTS.md")
        template = request.files.get("template")
        if template and template.filename:
            if Path(template.filename).suffix.lower() != ".docx":
                return jsonify(error="Report template must be a .docx file"), 400
            store.put(_key(g.cloud_user.workspace_id, NAMES["template"]), template.stream,
                      content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                      overwrite=True)
            changed.append("report template")
        if not changed:
            return jsonify(error="Choose at least one setting to save"), 400
        return jsonify(message="Saved " + ", ".join(changed) + ".")

    return blueprint


def load_secret(store, workspace_id):
    path = _download(store, workspace_id, NAMES["secret"])
    if path is None:
        return os.environ.get("ANTHROPIC_API_KEY", "").strip()
    try:
        return _cipher().decrypt(path.read_bytes()).decode()
    except InvalidToken as exc:
        raise RuntimeError("Stored Claude API key could not be decrypted") from exc
    finally:
        path.unlink(missing_ok=True)


def load_text(store, workspace_id):
    path = _download(store, workspace_id, NAMES["agents"])
    if path is None:
        return ""
    try:
        return path.read_text("utf-8")
    finally:
        path.unlink(missing_ok=True)


def download_template(store, workspace_id, destination):
    try:
        return store.download_to(_key(workspace_id, NAMES["template"]), Path(destination))
    except BlobNotFoundError:
        return None


def _cipher():
    secret = os.environ["FLASK_SECRET_KEY"].encode()
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret).digest()))


def _key(workspace_id, filename):
    return f"{workspace_id}/admin/{filename}"


def _exists(store, key):
    try:
        store.stat(key); return True
    except BlobNotFoundError:
        return False


def _download(store, workspace_id, filename):
    handle, name = tempfile.mkstemp(prefix="sitescribe-admin-")
    os.close(handle); path = Path(name)
    try:
        return store.download_to(_key(workspace_id, filename), path)
    except BlobNotFoundError:
        path.unlink(missing_ok=True); return None
