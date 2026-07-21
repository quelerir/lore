"""Unit tests for AuditApiSettings, specifically DSN credential escaping."""

from __future__ import annotations

import pytest

from lore_audit_api.settings import AuditApiSettings


def _make_settings(**overrides: str | int) -> AuditApiSettings:
    """Construct AuditApiSettings with required fields, bypassing .env."""
    defaults: dict = {
        "toast_db_host": "localhost",
        "toast_db_port": 5432,
        "toast_db_user": "user",
        "toast_db_password": "password",
        "toast_db_name": "loredb",
        "chainlit_jwt_secret": "secret",
    }
    defaults.update(overrides)
    return AuditApiSettings.model_validate(defaults)


class TestAuditDsnEscaping:
    """audit_dsn() must percent-encode special chars in user/password."""

    def test_plain_credentials_produce_valid_dsn(self) -> None:
        settings = _make_settings(toast_db_user="alice", toast_db_password="simple")
        dsn = settings.audit_dsn()
        assert dsn == "postgresql://alice:simple@localhost:5432/loredb"

    def test_at_sign_in_password_is_escaped(self) -> None:
        settings = _make_settings(toast_db_password="p@ss:w/rd")
        dsn = settings.audit_dsn()
        # The raw special characters must NOT appear in the userinfo segment
        # (everything before the last '@' that separates userinfo from host).
        userinfo, _, hostpart = dsn[len("postgresql://"):].rpartition("@")
        assert "@" not in userinfo, "raw '@' leaked into DSN userinfo"
        assert "/" not in userinfo, "raw '/' leaked into DSN userinfo"
        # Percent-encoded forms must be present
        assert "%40" in userinfo, "expected '%40' for '@'"
        assert "%3A" in userinfo or ":" not in userinfo.split(":")[1:], (
            "raw ':' in password should be percent-encoded"
        )
        assert "%2F" in userinfo, "expected '%2F' for '/'"

    def test_colon_in_password_is_escaped(self) -> None:
        settings = _make_settings(toast_db_password="pass:word")
        dsn = settings.audit_dsn()
        userinfo, _, _ = dsn[len("postgresql://"):].rpartition("@")
        _user, _, encoded_pw = userinfo.partition(":")
        assert ":" not in encoded_pw, "raw ':' should not appear in encoded password"
        assert "%3A" in encoded_pw

    def test_slash_in_password_is_escaped(self) -> None:
        settings = _make_settings(toast_db_password="pass/word")
        dsn = settings.audit_dsn()
        userinfo, _, _ = dsn[len("postgresql://"):].rpartition("@")
        _user, _, encoded_pw = userinfo.partition(":")
        assert "/" not in encoded_pw, "raw '/' should not appear in encoded password"
        assert "%2F" in encoded_pw

    def test_special_chars_in_user_are_escaped(self) -> None:
        settings = _make_settings(toast_db_user="us@er", toast_db_password="plain")
        dsn = settings.audit_dsn()
        userinfo, _, _ = dsn[len("postgresql://"):].rpartition("@")
        encoded_user, _, _ = userinfo.partition(":")
        assert "@" not in encoded_user
        assert "%40" in encoded_user

    def test_host_and_dbname_are_not_escaped(self) -> None:
        """Host and DB name should remain literal in the DSN."""
        settings = _make_settings(
            toast_db_host="db.example.com",
            toast_db_name="mydb",
            toast_db_password="plain",
        )
        dsn = settings.audit_dsn()
        assert "db.example.com" in dsn
        assert "/mydb" in dsn

    def test_port_is_included(self) -> None:
        settings = _make_settings(toast_db_port=5433, toast_db_password="plain")
        dsn = settings.audit_dsn()
        assert ":5433/" in dsn
