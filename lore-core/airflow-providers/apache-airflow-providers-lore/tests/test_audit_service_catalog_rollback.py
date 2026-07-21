"""Reinstated Phase-3 debt: the airflow-adapter catalog-rollback test excised
from the pure `test_audit_service` when the audit engine moved to lore-audit-core
(it needs `build_airflow_audit_adapters`). Verifies that a Postgres catalog
failure during payload resolution rolls back and persists a safe failed
lifecycle without leaking the connection canary.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from lore_audit.contracts import (
    AUDIT_FAILED,
    AuditPayloadOccurrence,
    AuditRun,
    AuditSnapshot,
)
from lore_audit.engine_contracts import PayloadResolutionFact, PhysicalResolution
from lore_audit.service import AuditExecutionError, AuditService
from lore_audit.snapshot_repository import AuditReadBounds, AuditSnapshotBundle
from lore_core_domain.run_status import RunStatus

RUN_ID = "00000000-0000-0000-0000-000000000021"


def bundle():
    now = datetime(2026, 7, 16, 9, 0, tzinfo=UTC)
    run = AuditRun(
        RUN_ID,
        "drive.files.audit",
        RunStatus.SUCCESS,
        "a" * 64,
        "b" * 64,
        "operator",
        "chunks",
        now,
        now + timedelta(seconds=1),
        0,
        0,
        0,
        0,
    )
    return AuditSnapshotBundle(AuditSnapshot("audit/v1", run, (), (), ()), ())


def payload_bundle():
    base = bundle().snapshot
    occurrence = AuditPayloadOccurrence(
        RUN_ID,
        "table-1",
        0,
        "table",
        "table-1",
        "a" * 64,
    )
    snapshot = AuditSnapshot("audit/v1", base.run, (), (occurrence,), ())
    fact = PayloadResolutionFact(
        "table-1",
        "table",
        True,
        1,
        {"schema_name": "lore_toast", "table_name": "table_1"},
        PhysicalResolution(
            "postgres",
            True,
            {"schema_name": "lore_toast", "table_name": "table_1"},
        ),
    )
    return AuditSnapshotBundle(snapshot, (fact,))


class Reader:
    def __init__(self, events, *, error=None, value=None):
        self.events = events
        self.error = error
        self.value = value
        self.calls = []

    def load_exact_run(self, run_id, ruleset_version, bounds):
        self.events.append("read")
        self.calls.append((run_id, ruleset_version, bounds))
        if self.error:
            raise self.error
        return self.value if self.value is not None else bundle()


class PoisonedCatalogConnection:
    def __init__(self, canary):
        self.canary = canary
        self.poisoned = False
        self.commits = 0
        self.rollbacks = 0
        self.statements = []

    def cursor(self):
        connection = self

        class Cursor:
            def execute(self, sql, params=()):
                if connection.poisoned:
                    raise RuntimeError("current transaction is aborted")
                connection.statements.append((" ".join(sql.split()), params))
                if "pg_catalog.pg_class" in sql:
                    connection.poisoned = True
                    raise RuntimeError(connection.canary)

            def fetchone(self):
                sql = connection.statements[-1][0]
                if "FOR KEY SHARE" in sql:
                    return (RUN_ID,)
                if "RETURNING" in sql:
                    return (1,)
                raise AssertionError(f"unexpected fetchone for {sql}")

            def close(self):
                pass

        return Cursor()

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1
        self.poisoned = False


def test_catalog_failure_rolls_back_before_service_persists_resolution_failure():
    from airflow.providers.lore.adapters.airflow_audit_adapters import (
        build_airflow_audit_adapters,
    )

    canary = "postgresql://user:password@host/db SELECT private source text"
    connection = PoisonedCatalogConnection(canary)
    adapters = build_airflow_audit_adapters(
        "postgres",
        "s3",
        postgres_hook=type("Hook", (), {"get_conn": lambda self: connection})(),
        s3_hook=object(),
    )
    value = AuditService(
        Reader([], value=payload_bundle()),
        adapters.writer,
        AuditReadBounds(),
        payload_resolver=adapters.payload_resolver,
    )

    with pytest.raises(AuditExecutionError) as error:
        value.audit_run(RUN_ID)

    assert error.value.category == "resolution_failed"
    assert str(error.value) == "audit dependency resolution failed"
    assert canary not in str(error.value)
    assert connection.rollbacks == 1
    assert connection.commits == 1
    _, params = connection.statements[-1]
    assert params[1] == AUDIT_FAILED
    assert params[3].obj["diagnostic"]["details"]["category"] == "resolution_failed"
