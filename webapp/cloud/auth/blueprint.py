"""Flask routes and request guard for Supabase email/password sign-in."""

from __future__ import annotations

import functools

from flask import Blueprint, g, jsonify, redirect, render_template_string, request, session

from .client import AuthError, SupabaseAuthClient
from .pkce import create_pkce_pair
from .service import AuthenticationService, SignInRejected


SESSION_KEY = "cloud_sid"

LOGIN_HTML = """<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sign in - MKA Site Visit Buddy</title><style>
:root{font:16px/1.5 system-ui;color:#182132;background:#f3f6fa}
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;padding:20px}
main{width:min(100%,380px);background:white;border:1px solid #dce3ec;border-radius:18px;padding:26px}
h1{margin:0 0 6px}.muted{color:#66758a;margin:0 0 22px}
label{display:block;margin:13px 0 5px;font-weight:650}input,button{width:100%;font:inherit;padding:12px;
border:1px solid #b9c5d4;border-radius:9px}button{margin-top:18px;background:#1769e0;color:white;border:0;font-weight:700}
.error{color:#a62d25;margin-top:14px}</style></head><body><main>
<h1>MKA Site Visit Buddy</h1><p class="muted">Trial account sign in</p>
<form method="post"><label for="email">Email</label>
<input id="email" name="email" type="email" autocomplete="username" required autofocus>
<label for="password">Password</label>
<input id="password" name="password" type="password" autocomplete="current-password" required>
<button type="submit">Sign in</button></form>
{% if error %}<div class="error" role="alert">{{ error }}</div>{% endif %}
</main></body></html>"""


def create_auth_blueprint(
    client: SupabaseAuthClient, service: AuthenticationService
) -> Blueprint:
    blueprint = Blueprint("cloud_auth", __name__)

    @blueprint.route("/auth/login", methods=["GET", "POST"])
    def login():
        if request.method == "GET":
            return render_template_string(LOGIN_HTML, error=None)
        try:
            provider_session = client.password_sign_in(
                request.form.get("email", ""), request.form.get("password", "")
            )
            signed_in = service.establish(provider_session.user, provider_session)
        except AuthError:
            return render_template_string(
                LOGIN_HTML, error="Incorrect email or password."
            ), 401
        except SignInRejected as exc:
            return render_template_string(LOGIN_HTML, error=str(exc)), 403
        session.clear()
        session.permanent = True
        session[SESSION_KEY] = signed_in.opaque_session_id
        return redirect("/pending" if signed_in.status != "active" else "/")

    @blueprint.get("/auth/callback")
    def callback():
        expected = session.pop("oauth_state", "")
        verifier = session.pop("oauth_verifier", "")
        if not expected or request.args.get("state") != expected:
            return jsonify(error="invalid sign-in state"), 400
        try:
            provider_session = client.exchange_code(request.args.get("code", ""), verifier)
            signed_in = service.establish(provider_session.user, provider_session)
        except (AuthError, SignInRejected) as exc:
            return jsonify(error=str(exc)), 403
        session.clear()
        session.permanent = True
        session[SESSION_KEY] = signed_in.opaque_session_id
        if signed_in.status != "active":
            return redirect("/pending")
        return redirect("/")

    @blueprint.post("/auth/logout")
    def logout():
        service.revoke(session.get(SESSION_KEY, ""))
        session.clear()
        return "", 204

    @blueprint.get("/api/me")
    @require_cloud_user(service)
    def me():
        user = g.cloud_user
        return jsonify(
            id=str(user.profile_id),
            email=user.email,
            workspace_id=str(user.workspace_id),
            role=user.role,
            status=user.status,
        )

    @blueprint.get("/pending")
    def pending():
        user = service.resolve(session.get(SESSION_KEY, ""))
        if user is None:
            return redirect("/auth/login")
        if user.status == "active":
            return redirect("/")
        return (
            "<!doctype html><title>Access pending</title>"
            "<h1>Access pending</h1>"
            "<p>An administrator must activate your MKA Site Visit Buddy membership.</p>",
            403,
        )

    return blueprint


def require_cloud_user(service: AuthenticationService, *, redirect_to_login: bool = False):
    def decorate(fn):
        @functools.wraps(fn)
        def guarded(*args, **kwargs):
            user = service.resolve(session.get(SESSION_KEY, ""))
            if user is None:
                if redirect_to_login:
                    return redirect("/auth/login")
                return jsonify(error="authentication required"), 401
            if user.status != "active":
                return jsonify(error="active membership required"), 403
            g.cloud_user = user
            return fn(*args, **kwargs)

        return guarded

    return decorate
