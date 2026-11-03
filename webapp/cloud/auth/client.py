"""Request-scoped client for Supabase Auth."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

import requests

from .config import AuthConfig
from .pkce import PkcePair


class AuthError(RuntimeError):
    """A safe authentication error suitable for translating to HTTP 401."""


@dataclass(frozen=True)
class AuthUser:
    id: str
    email: str
    provider: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AuthSession:
    access_token: str
    refresh_token: str
    expires_in: int
    token_type: str
    user: AuthUser


class SupabaseAuthClient:
    def __init__(self, config: AuthConfig, http: Any = requests):
        self.config = config
        self.http = http
        self._headers = {"apikey": config.publishable_key, "Content-Type": "application/json"}

    def authorization_url(self, pair: PkcePair) -> str:
        query = urlencode({
            "provider": "azure",
            "redirect_to": self.config.callback_url,
            "scopes": "email",
            "code_challenge": pair.challenge,
            "code_challenge_method": "s256",
            "state": pair.state,
        })
        return f"{self.config.supabase_url}/auth/v1/authorize?{query}"

    def exchange_code(self, code: str, verifier: str) -> AuthSession:
        if not code or not verifier:
            raise AuthError("The sign-in response was incomplete.")
        return _session(self._post(
            "/auth/v1/token?grant_type=pkce",
            {"auth_code": code, "code_verifier": verifier},
        ))

    def refresh(self, refresh_token: str) -> AuthSession:
        if not refresh_token:
            raise AuthError("Your session has expired.")
        return _session(self._post(
            "/auth/v1/token?grant_type=refresh_token",
            {"refresh_token": refresh_token},
        ))

    def user(self, access_token: str) -> AuthUser:
        if not access_token:
            raise AuthError("Authentication is required.")
        response = self.http.get(
            self.config.supabase_url + "/auth/v1/user",
            headers={**self._headers, "Authorization": f"Bearer {access_token}"},
            timeout=15,
        )
        return _user(self._json(response))

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self.http.post(
            self.config.supabase_url + path,
            headers=self._headers,
            json=payload,
            timeout=15,
        )
        return self._json(response)

    @staticmethod
    def _json(response: Any) -> dict[str, Any]:
        try:
            data = response.json()
        except (TypeError, ValueError) as exc:
            raise AuthError("The authentication service returned invalid data.") from exc
        if not getattr(response, "ok", False):
            message = data.get("msg") or data.get("error_description") or data.get("error")
            raise AuthError(str(message or "Authentication failed."))
        if not isinstance(data, dict):
            raise AuthError("The authentication service returned invalid data.")
        return data


def _user(data: dict[str, Any]) -> AuthUser:
    user_id = str(data.get("id") or "")
    email = str(data.get("email") or "").strip().lower()
    if not user_id or not email:
        raise AuthError("Microsoft did not provide a usable user identity.")
    app = data.get("app_metadata") if isinstance(data.get("app_metadata"), dict) else {}
    meta = data.get("user_metadata") if isinstance(data.get("user_metadata"), dict) else {}
    return AuthUser(user_id, email, str(app.get("provider") or ""), dict(meta))


def _session(data: dict[str, Any]) -> AuthSession:
    access = str(data.get("access_token") or "")
    refresh = str(data.get("refresh_token") or "")
    if not access or not refresh:
        raise AuthError("The authentication service did not create a session.")
    try:
        expires = int(data.get("expires_in") or 0)
    except (TypeError, ValueError) as exc:
        raise AuthError("The authentication session expiry was invalid.") from exc
    user_data = data.get("user") if isinstance(data.get("user"), dict) else {}
    return AuthSession(access, refresh, max(1, expires),
                       str(data.get("token_type") or "bearer"), _user(user_data))

