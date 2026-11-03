"""Flask routes and request guard for Microsoft sign-in through Supabase."""

from __future__ import annotations

import functools

from flask import Blueprint, g, jsonify, redirect, request, session

from .client import AuthError, SupabaseAuthClient
from .pkce import create_pkce_pair
from .service import AuthenticationService, SignInRejected


SESSION_KEY = "cloud_sid"


def create_auth_blueprint(
    client: SupabaseAuthClient, service: AuthenticationService
) -> Blueprint:
    blueprint = Blueprint("cloud_auth", __name__)

    @blueprint.get("/auth/login")
    def login():
        pair = create_pkce_pair()
        session["oauth_state"] = pair.state
        session["oauth_verifier"] = pair.verifier
        return redirect(client.authorization_url(pair))

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
            "<p>An administrator must activate your SiteScribe membership.</p>",
            403,
        )

    return blueprint


def require_cloud_user(service: AuthenticationService):
    def decorate(fn):
        @functools.wraps(fn)
        def guarded(*args, **kwargs):
            user = service.resolve(session.get(SESSION_KEY, ""))
            if user is None:
                return jsonify(error="authentication required"), 401
            if user.status != "active":
                return jsonify(error="active membership required"), 403
            g.cloud_user = user
            return fn(*args, **kwargs)

        return guarded

    return decorate
