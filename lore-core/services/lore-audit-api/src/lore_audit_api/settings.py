"""Pydantic settings for the standalone lore-audit-api sidecar.

Reads the CANONICAL env names (no aliases). The audit DB is the same physical
instance as the chat's Toast DB (schema lore_core); `chainlit_jwt_secret` is the
single canonical source for both the cursor HMAC key and the datacraft ticket
signing key.
"""

from __future__ import annotations

import hashlib

from pydantic_settings import BaseSettings, SettingsConfigDict


class AuditApiSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Canonical lore_core DB vars (same physical DB as chat TOAST) — no aliases.
    toast_db_host: str
    toast_db_port: int = 5432
    toast_db_user: str
    toast_db_password: str
    toast_db_name: str

    # cursor HMAC key source + datacraft HS256 ticket signing key (one canonical name).
    chainlit_jwt_secret: str
    # datacraft ticket audience/issuer for standalone ticket verification.
    chainlit_jwt_audience: str | None = None
    chainlit_jwt_issuer: str | None = None

    def audit_dsn(self) -> str:
        return (
            f"postgresql://{self.toast_db_user}:{self.toast_db_password}"
            f"@{self.toast_db_host}:{self.toast_db_port}/{self.toast_db_name}"
        )

    def cursor_key(self) -> bytes:
        """Domain-separated 32-byte HMAC key derived from the JWT secret.

        Matches the chat's derivation so cursors stay valid across both mounts.
        """
        return hashlib.sha256(
            b"audit-cursor-v1|" + self.chainlit_jwt_secret.encode("utf-8")
        ).digest()


__all__ = ["AuditApiSettings"]
