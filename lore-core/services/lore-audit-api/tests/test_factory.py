"""Factory assembly tests (folds in the retired chat test_audit_assembly)."""

from __future__ import annotations

import lore_audit_api.factory as factory
from lore_audit.read_service import AuditReadService


class _FakePool:
    def acquire(self):  # pragma: no cover - never invoked in assembly
        raise AssertionError("no connection should be acquired during assembly")

    def close(self):  # pragma: no cover
        pass


def test_build_audit_service_assembles_read_service_from_dsn_and_key(monkeypatch):
    captured = {}

    def _fake_build_pool(dsn, **kwargs):
        captured["dsn"] = dsn
        return _FakePool()

    monkeypatch.setattr(factory, "build_audit_pool", _fake_build_pool)

    service = factory.build_audit_service(
        dsn="postgresql://u:p@db:5432/lore",
        cursor_key=b"k" * 32,
    )

    assert isinstance(service, AuditReadService)
    assert captured["dsn"] == "postgresql://u:p@db:5432/lore"
    # A default Postgres table reader is wired unless one is injected.
    assert service._table_reader is not None


def test_build_audit_service_honours_injected_readers(monkeypatch):
    monkeypatch.setattr(factory, "build_audit_pool", lambda dsn, **k: _FakePool())
    sentinel = object()

    service = factory.build_audit_service(
        dsn="postgresql://u:p@db:5432/lore",
        cursor_key=b"k" * 32,
        table_reader=sentinel,
    )

    assert service._table_reader is sentinel
