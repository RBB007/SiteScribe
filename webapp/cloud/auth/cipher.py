"""Encryption for provider tokens held in server-side auth sessions."""

from __future__ import annotations

import os

from cryptography.fernet import Fernet, InvalidToken, MultiFernet


class TokenCipherError(RuntimeError):
    pass


class TokenCipher:
    def __init__(self, keys: list[str]):
        cleaned = [key.strip() for key in keys if key.strip()]
        if not cleaned:
            raise TokenCipherError("AUTH_TOKEN_ENCRYPTION_KEYS is required")
        try:
            self._cipher = MultiFernet([Fernet(key.encode("ascii")) for key in cleaned])
        except (TypeError, ValueError) as exc:
            raise TokenCipherError("AUTH_TOKEN_ENCRYPTION_KEYS is invalid") from exc

    @classmethod
    def from_env(cls) -> "TokenCipher":
        return cls(os.environ.get("AUTH_TOKEN_ENCRYPTION_KEYS", "").split(","))

    def encrypt(self, value: str) -> str:
        if not value:
            raise TokenCipherError("cannot encrypt an empty token")
        return self._cipher.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, value: str) -> str:
        try:
            return self._cipher.decrypt(value.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeError, ValueError) as exc:
            raise TokenCipherError("stored token cannot be decrypted") from exc

    def rotate(self, value: str) -> str:
        try:
            return self._cipher.rotate(value.encode("ascii")).decode("ascii")
        except (InvalidToken, ValueError) as exc:
            raise TokenCipherError("stored token cannot be rotated") from exc
