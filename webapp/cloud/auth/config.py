"""Environment-backed authentication configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AuthConfig:
    supabase_url: str
    publishable_key: str
    azure_tenant_id: str
    app_base_url: str
    bootstrap_admin_email: str = ""
    cookie_secure: bool = True

    @classmethod
    def from_env(cls) -> "AuthConfig":
        values = {
            "supabase_url": os.environ.get("SUPABASE_URL", "").rstrip("/"),
            "publishable_key": os.environ.get("SUPABASE_PUBLISHABLE_KEY", ""),
            "app_base_url": os.environ.get("APP_BASE_URL", "").rstrip("/"),
        }
        missing = [name.upper() for name, value in values.items() if not value]
        if missing:
            raise RuntimeError("Missing authentication configuration: " + ", ".join(missing))
        return cls(
            **values,
            azure_tenant_id=os.environ.get("AZURE_TENANT_ID", ""),
            bootstrap_admin_email=os.environ.get("BOOTSTRAP_ADMIN_EMAIL", "").strip().lower(),
            cookie_secure=os.environ.get("AUTH_COOKIE_SECURE", "true").lower()
            not in {"0", "false", "no"},
        )

    @property
    def callback_url(self) -> str:
        return self.app_base_url + "/auth/callback"
