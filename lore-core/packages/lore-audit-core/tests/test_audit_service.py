from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from lore_audit.contracts import (
    AUDIT_COMPLETED,
    AUDIT_FAILED,
    AuditLifecycleResult,
    AuditPayloadOccurrence,
    AuditRun,
    AuditSnapshot,
    LifecycleDiagnostic,
    LifecycleOutcome,
    RuleOutcome,
    Severity,
)
from lore_audit.engine_contracts import (
    AuditEngineResult,
    PayloadResolutionFact,
    PhysicalResolution,
)
from lore_audit.snapshot_repository import AuditReadBounds, AuditSnapshotBundle
from lore_audit.service import (
    AuditExecutionError,
    AuditService,
)
from lore_core_domain.run_status import RunStatus

RUN_ID = "00000000-0000-0000-0000-000000000021"
CANARIES = (
    "postgresql://user:password@host/db",
    "secret-password",
    "https://bucket.invalid/key?X-Amz-Signature=secret",
    "SELECT source_text FROM private_table",
    "private source text",
    "payload-bytes-secret",
)


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


def completed():
    lifecycle = AuditLifecycleResult(
        LifecycleOutcome.COMPLETED,
        "audit/v1",
        RUN_ID,
        AUDIT_COMPLETED,
        0,
        {outcome: 0 for outcome in RuleOutcome},
        {severity: 0 for severity in Severity},
        None,
    )
    return AuditEngineResult((), lifecycle)


def engine_failed():
    lifecycle = AuditLifecycleResult(
        LifecycleOutcome.FAILED,
        "audit/v1",
        RUN_ID,
        AUDIT_FAILED,
        None,
        None,
        None,
        LifecycleDiagnostic(
            AUDIT_FAILED,
            "Audit evaluation failed closed",
            {"failed_rule_id": "terminal_status", "exception_class": "RuntimeError"},
        ),
    )
    return AuditEngineResult((), lifecycle)


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


class Resolver:
    def __init__(self, events, *, error=None, output=None):
        self.events = events
        self.error = error
        self.output = output
        self.calls = []

    def resolve(self, facts):
        self.events.append("resolve")
        self.calls.append(facts)
        if self.error:
            raise self.error
        return self.output(facts) if self.output is not None else facts


class Writer:
    def __init__(self, events, *, completed_error=None, failed_error=None):
        self.events = events
        self.completed_error = completed_error
        self.failed_error = failed_error
        self.completed = []
        self.failed = []

    def write_completed(self, result):
        self.events.append("write_completed")
        self.completed.append(result)
        if self.completed_error:
            raise self.completed_error

    def write_failed(self, lifecycle):
        self.events.append("write_failed")
        self.failed.append(lifecycle)
        if self.failed_error:
            raise self.failed_error


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


def service(
    *,
    read_error=None,
    resolve_error=None,
    resolver_output=None,
    bundle_value=None,
    engine=None,
    write_error=None,
    failed_error=None,
):
    events = []
    reader = Reader(events, error=read_error, value=bundle_value)
    resolver = Resolver(events, error=resolve_error, output=resolver_output)
    writer = Writer(events, completed_error=write_error, failed_error=failed_error)

    def audit_engine(engine_input):
        events.append("engine")
        assert engine_input.snapshot.run.run_id == RUN_ID
        assert engine_input.ruleset_version == "audit/v1"
        assert engine_input.token_facts == ()
        return (engine or completed)()

    value = AuditService(
        reader=reader,
        writer=writer,
        bounds=AuditReadBounds(),
        payload_resolver=resolver,
        engine=audit_engine,
    )
    return value, events, reader, resolver, writer


def test_service_composes_exact_read_resolution_engine_and_completed_write():
    value, events, reader, resolver, writer = service()

    result = value.audit_run(RUN_ID, "audit/v1")

    assert events == ["read", "resolve", "engine", "write_completed"]
    assert reader.calls == [(RUN_ID, "audit/v1", value.bounds)]
    assert resolver.calls == [()]
    assert writer.failed == []
    assert result.to_dict() == {
        "run_id": RUN_ID,
        "ruleset_version": "audit/v1",
        "status": "completed",
        "checked_rule_count": 0,
        "outcome_counts": {outcome.value: 0 for outcome in RuleOutcome},
        "severity_counts": {severity.value: 0 for severity in Severity},
    }


def test_service_can_use_explicitly_absent_optional_resolver():
    events = []
    reader = Reader(events)
    writer = Writer(events)

    AuditService(reader, writer, AuditReadBounds(), engine=lambda _: completed()).audit_run(
        RUN_ID, "audit/v1"
    )

    assert events == ["read", "write_completed"]


@pytest.mark.parametrize(
    ("kwargs", "expected_events", "category", "stage"),
    (
        ({"read_error": RuntimeError("read")}, ["read", "write_failed"], "read_failed", "read"),
        (
            {"resolve_error": RuntimeError("resolve")},
            ["read", "resolve", "write_failed"],
            "resolution_failed",
            "resolution",
        ),
        (
            {"engine": lambda: (_ for _ in ()).throw(RuntimeError("engine"))},
            ["read", "resolve", "engine", "write_failed"],
            "engine_failed",
            "engine",
        ),
        (
            {"engine": engine_failed},
            ["read", "resolve", "engine", "write_failed"],
            "engine_failed",
            "engine",
        ),
        (
            {"write_error": RuntimeError("write")},
            ["read", "resolve", "engine", "write_completed", "write_failed"],
            "completed_write_failed",
            "completed_write",
        ),
    ),
)
def test_primary_failures_write_one_safe_failed_lifecycle(kwargs, expected_events, category, stage):
    value, events, _, _, writer = service(**kwargs)

    with pytest.raises(AuditExecutionError) as error:
        value.audit_run(RUN_ID, "audit/v1")

    assert error.value.category == category
    assert events == expected_events
    assert len(writer.failed) == 1
    details = writer.failed[0].to_dict()["diagnostic"]["details"]
    assert details == {
        "category": category,
        "ruleset_version": "audit/v1",
        "stage": stage,
    }
    assert error.value.__cause__ is not None


def test_secondary_failure_preserves_primary_cause_and_exposes_fixed_combined_category():
    primary = RuntimeError("primary " + " ".join(CANARIES))
    secondary = RuntimeError("secondary " + " ".join(CANARIES))
    value, events, _, _, _ = service(read_error=primary, failed_error=secondary)

    with pytest.raises(AuditExecutionError) as error:
        value.audit_run(RUN_ID, "audit/v1")

    assert events == ["read", "write_failed"]
    assert error.value.category == "failure_recording_failed"
    assert error.value.__cause__ is primary
    public = str(error.value) + repr(error.value)
    assert all(canary not in public for canary in CANARIES)


def test_invalid_run_or_ruleset_is_rejected_before_any_dependency_call():
    value, events, _, _, writer = service()

    for run_id, ruleset in (("not-a-uuid", "audit/v1"), (RUN_ID, "audit/v2")):
        with pytest.raises(AuditExecutionError) as error:
            value.audit_run(run_id, ruleset)
        assert error.value.category == "invalid_request"

    assert events == []
    assert writer.completed == writer.failed == []


def test_exception_canaries_never_reach_public_error_or_failed_lifecycle():
    raw = RuntimeError(" ".join(CANARIES))
    value, _, _, _, writer = service(resolve_error=raw)

    with pytest.raises(AuditExecutionError) as error:
        value.audit_run(RUN_ID, "audit/v1")

    public = str(error.value) + repr(error.value) + repr(writer.failed[0].to_dict())
    assert all(canary not in public for canary in CANARIES)


def _mutated_table_fact(fact, **changes):
    projection = fact.to_dict()
    physical = projection.pop("physical")
    projection.update(changes)
    return PayloadResolutionFact(**projection, physical=PhysicalResolution(**physical))


@pytest.mark.parametrize(
    "resolver_output",
    (
        lambda _facts: (),
        lambda facts: (
            *facts,
            PayloadResolutionFact("decoy", "table", False, 1),
        ),
        lambda facts: (facts[0], facts[0]),
        lambda facts: (_mutated_table_fact(facts[0], occurrence_count=2),),
        lambda facts: (
            _mutated_table_fact(
                facts[0],
                registration_identity={"schema_name": "other", "table_name": "table_1"},
            ),
        ),
    ),
    ids=("dropped", "added", "duplicated", "count-mutated", "identity-mutated"),
)
def test_service_rejects_resolver_membership_or_registration_mutation(resolver_output):
    value, events, _, _, writer = service(
        bundle_value=payload_bundle(), resolver_output=resolver_output
    )

    with pytest.raises(AuditExecutionError) as error:
        value.audit_run(RUN_ID)

    assert error.value.category == "resolution_failed"
    assert events == ["read", "resolve", "write_failed"]
    assert writer.completed == []
