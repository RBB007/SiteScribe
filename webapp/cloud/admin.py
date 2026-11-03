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
from webapp.cloud.storage import BlobStoreError


SECRET_NAME = "claude_api_key.enc"


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
        configured = _exists(store, _key(g.cloud_user.workspace_id, SECRET_NAME))
        return jsonify(secret=configured or bool(os.environ.get("ANTHROPIC_API_KEY", "").strip()))

    @blueprint.post("/api/admin/settings")
    @admin_only(redirect_to_login=False)
    def update():
        api_key = request.form.get("api_key", "").strip()
        if not api_key:
            return jsonify(error="Enter a Claude API key"), 400
        encrypted = _cipher().encrypt(api_key.encode())
        store.put(_key(g.cloud_user.workspace_id, SECRET_NAME), encrypted,
                  content_type="text/plain", overwrite=True)
        return jsonify(message="Claude API key saved.")

    return blueprint


def load_secret(store, workspace_id):
    path = _download(store, workspace_id, SECRET_NAME)
    if path is None:
        return os.environ.get("ANTHROPIC_API_KEY", "").strip()
    try:
        return _cipher().decrypt(path.read_bytes()).decode()
    except InvalidToken as exc:
        raise RuntimeError("Stored Claude API key could not be decrypted") from exc
    finally:
        path.unlink(missing_ok=True)


def _cipher():
    secret = os.environ["FLASK_SECRET_KEY"].encode()
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret).digest()))


def _key(workspace_id, filename):
    return f"{workspace_id}/admin/{filename}"


def _exists(store, key):
    path = _download_key(store, key)
    if path is None:
        return False
    try:
        return True
    finally:
        path.unlink(missing_ok=True)


def _download(store, workspace_id, filename):
    return _download_key(store, _key(workspace_id, filename))


def _download_key(store, key):
    handle, name = tempfile.mkstemp(prefix="sitescribe-admin-")
    os.close(handle); path = Path(name)
    try:
        return store.download_to(key, path)
    except BlobStoreError:
        path.unlink(missing_ok=True); return None
