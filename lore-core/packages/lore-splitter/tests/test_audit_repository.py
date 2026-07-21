from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime

import pytest
from psycopg.types.json import Jsonb

from lore_audit.contracts import (
    AuditPayloadOccurrence,
    AuditRun,
    AuditSnapshot,
)
from lore_audit.snapshot_repository import (
    AuditReadBounds,
    AuditRepositoryError,
    AuditSnapshotBundle,
    PostgresAuditSnapshotRepository,
)
from lore_audit.registration import parse_payload_registration
from lore_splitter.per_file import RunStatus
from lore_splitter.storage.core_schema import apply_migration
from postgres_test_harness import ephemeral_postgres


RUN_A = "00000000-0000-0000-0000-000000000001"
RUN_B = "00000000-0000-0000-0000-000000000002"
SHA_A = "a" * 64


def run(run_id=RUN_B, **overrides):
    values = {
        "run_id": run_id,
        "logical_file_key": "drive.files.b",
        "status": RunStatus.SUCCESS,
        "source_content_hash": "b" * 64,
        "config_hash": "c" * 64,
        "operator_version": "1.3.0",
        "chunk_schema_version": "chunk/v1",
        "claimed_at": datetime(2026, 7, 16, tzinfo=UTC),
        "finished_at": datetime(2026, 7, 16, 0, 0, 1, tzinfo=UTC),
        "chunk_count": 0,
        "payload_count": 2,
        "warning_count": 0,
        "error_count": 0,
    }
    values.update(overrides)
    return AuditRun(**values)


def occurrence(payload_id="payload-1", ordinal=0, **overrides):
    values = {
        "run_id": RUN_B,
        "payload_id": payload_id,
        "occurrence_ordinal": ordinal,
        "kind": "table",
        "storage_identity": payload_id,
        "content_hash": SHA_A,
    }
    values.update(overrides)
    return AuditPayloadOccurrence(**values)


def snapshot(*occurrences):
    return AuditSnapshot(
        ruleset_version="audit/v1",
        run=run(payload_count=len(occurrences)),
        chunks=(),
        payload_occurrences=occurrences,
        processing_diagnostics=(),
    )


def registration(payload_id="payload-1"):
    return {
        "schema_version": "audit/payload-registration/v1",
        "payload_id": payload_id,
        "kind": "table",
        "backend": "postgres",
        "registration_identity": {
            "schema_name": "lore_toast",
            "table_name": f"toast_{payload_id.replace('-', '_')}",
            "row_count": 2,
        },
        "metadata": {"row_count": 2},
        "summary": {"row_count": 2},
    }


def image_registration(payload_id="image-1", checksum=SHA_A):
    return {
        "schema_version": "audit/payload-registration/v1",
        "payload_id": payload_id,
        "kind": "image",
        "backend": "s3",
        "registration_identity": {
            "bucket": "lore-images",
            "object_key": f"toast/{payload_id}.png",
            "content_type": "image/png",
            "extension": ".png",
            "byte_size": 12,
            "checksum_sha256": checksum,
        },
        "metadata": {
            "content_type": "image/png",
            "extension": ".png",
            "byte_size": 12,
            "checksum_sha256": checksum,
        },
        "summary": {},
    }


def payload_row(payload_id="payload-1", **overrides):
    value = {
        "payload_id": payload_id,
        "owner_run_id": RUN_A,
        "logical_file_key": "drive.files.a",
        "kind": "table",
        "storage": "table",
        "storage_identity": payload_id,
        "content_hash": SHA_A,
        "metadata": {"audit_registration": registration(payload_id)},
    }
    value.update(overrides)
    return value


def test_bounds_are_frozen_positive_and_capped():
    bounds = AuditReadBounds()
    assert bounds.max_chunks > 0
    assert bounds.max_aggregate_text_bytes >= bounds.max_text_bytes
    with pytest.raises(FrozenInstanceError):
        bounds.max_chunks = 2
    with pytest.raises(ValueError, match="^invalid audit read bounds$"):
        AuditReadBounds(max_chunks=0)
    with pytest.raises(ValueError, match="^invalid audit read bounds$"):
        AuditReadBounds(max_chunks=1_000_001)


def test_bundle_membership_comes_only_from_occurrences_and_accepts_first_owner_reuse():
    exact = snapshot(occurrence(), occurrence(ordinal=1))
    bundle = AuditSnapshotBundle.from_payload_rows(exact, [payload_row()])

    assert bundle.snapshot is exact
    assert bundle.token_facts == ()
    assert [fact.payload_id for fact in bundle.payload_facts] == ["payload-1"]
    assert bundle.payload_facts[0].occurrence_count == 2
    assert bundle.payload_facts[0].registered is True


def test_absent_registration_is_explicitly_unavailable_but_present_invalid_fails():
    exact = snapshot(occurrence())
    unavailable = AuditSnapshotBundle.from_payload_rows(
        exact, [payload_row(metadata={"legacy": True})]
    )
    assert unavailable.payload_facts[0].registered is False
    assert unavailable.payload_facts[0].physical is None

    with pytest.raises(AuditRepositoryError) as error:
        AuditSnapshotBundle.from_payload_rows(
            exact,
            [payload_row(metadata={"audit_registration": {"schema_version": "wrong"}})],
        )
    assert error.value.category == "snapshot_invalid"
    assert "wrong" not in str(error.value)


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [payload_row(), payload_row()],
        [payload_row(), payload_row("decoy")],
    ],
)
def test_bundle_rejects_missing_duplicate_and_unreferenced_payload_rows(rows):
    with pytest.raises(AuditRepositoryError) as error:
        AuditSnapshotBundle.from_payload_rows(snapshot(occurrence()), rows)
    assert error.value.category == "snapshot_invalid"


@pytest.mark.parametrize(
    "row_overrides",
    [
        {"kind": "image"},
        {"content_hash": "b" * 64},
        {"storage": "image"},
        {"storage_identity": "different"},
    ],
)
def test_bundle_rejects_incompatible_global_payload_evidence(row_overrides):
    with pytest.raises(AuditRepositoryError) as error:
        AuditSnapshotBundle.from_payload_rows(
            snapshot(occurrence()), [payload_row(**row_overrides)]
        )
    assert error.value.category == "snapshot_invalid"


def test_bundle_rejects_mixed_run_snapshot_and_has_no_token_input():
    mixed = object.__new__(AuditSnapshot)
    object.__setattr__(mixed, "ruleset_version", "audit/v1")
    object.__setattr__(mixed, "run", run())
    object.__setattr__(mixed, "chunks", ())
    object.__setattr__(mixed, "payload_occurrences", (replace(occurrence(), run_id=RUN_A),))
    object.__setattr__(mixed, "processing_diagnostics", ())

    with pytest.raises(AuditRepositoryError):
        AuditSnapshotBundle.from_payload_rows(mixed, [payload_row()])
    assert "token_facts" not in AuditSnapshotBundle.from_payload_rows.__annotations__


def test_bundle_constructor_rechecks_fact_kind_and_occurrence_count():
    exact = snapshot(occurrence(), occurrence(ordinal=1))
    fact = parse_payload_registration(
        "payload-1",
        "table",
        {"audit_registration": registration()},
        occurrence_count=1,
    )
    with pytest.raises(AuditRepositoryError):
        AuditSnapshotBundle(snapshot=exact, payload_facts=(fact,))


def test_bundle_rejects_image_registration_checksum_mismatch():
    exact = snapshot(
        occurrence(
            payload_id="image-1",
            kind="image",
            storage_identity="image-1",
        )
    )
    row = payload_row(
        payload_id="image-1",
        kind="image",
        storage="image",
        storage_identity="image-1",
        metadata={"audit_registration": image_registration(checksum="b" * 64)},
    )
    with pytest.raises(AuditRepositoryError) as error:
        AuditSnapshotBundle.from_payload_rows(exact, [row])
    assert error.value.category == "snapshot_invalid"


class ScriptedCursor:
    def __init__(self, result_sets, fail_on=None):
        self.result_sets = result_sets
        self.fail_on = fail_on
        self.statements = []
        self.current = []
        self.closed = False

    def execute(self, sql, params=()):
        self.statements.append((sql, params))
        if self.fail_on and self.fail_on in sql:
            raise RuntimeError("postgresql://user:password@host/db?token=canary")
        self.current = []
        for marker, rows in self.result_sets.items():
            if marker in sql:
                self.current = list(rows)
                break

    def fetchone(self):
        return self.current.pop(0) if self.current else None

    def fetchall(self):
        rows, self.current = self.current, []
        return rows

    def close(self):
        self.closed = True


class ScriptedConnection:
    def __init__(self, result_sets=None, fail_on=None):
        self.cursor_obj = ScriptedCursor(result_sets or {}, fail_on=fail_on)
        self.cursor_calls = 0
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        self.cursor_calls += 1
        return self.cursor_obj

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def run_row(status="success", **overrides):
    values = {
        "run_id": RUN_B,
        "logical_file_key": "drive.files.b",
        "status": status,
        "source_content_hash": "b" * 64,
        "config_hash": "c" * 64,
        "operator_version": "1.3.0",
        "chunk_schema_version": "chunk/v1",
        "claimed_at": datetime(2026, 7, 16, tzinfo=UTC),
        "finished_at": datetime(2026, 7, 16, 0, 0, 1, tzinfo=UTC),
        "chunk_count": 0,
        "payload_count": 1,
        "warning_count": 0,
        "error_count": 0,
    }
    values.update(overrides)
    return tuple(values.values())


def occurrence_row(payload_id="payload-1", **overrides):
    values = {
        "run_id": RUN_B,
        "payload_id": payload_id,
        "occurrence_ordinal": 0,
        "kind": "table",
        "storage_identity": payload_id,
        "content_hash": SHA_A,
        "coordinates": {},
        "metadata": {},
    }
    values.update(overrides)
    return tuple(values.values())


def global_payload_row(payload_id="payload-1", **overrides):
    values = {
        "payload_id": payload_id,
        "owner_run_id": RUN_A,
        "logical_file_key": "drive.files.a",
        "kind": "table",
        "storage": "table",
        "storage_identity": payload_id,
        "content_hash": SHA_A,
        "metadata": {"audit_registration": registration(payload_id)},
    }
    values.update(overrides)
    return tuple(values.values())


def scripted_connection(**overrides):
    result_sets = {
        "FROM lore_core.processing_runs": [run_row()],
        "FROM lore_core.chunks": [],
        "FROM lore_core.payload_occurrences": [occurrence_row()],
        "FROM lore_core.diagnostics": [],
        "FROM lore_core.payloads": [global_payload_row()],
    }
    result_sets.update(overrides)
    return ScriptedConnection(result_sets)


def test_postgres_reader_uses_only_exact_run_queries_stable_order_and_bounds():
    connection = scripted_connection()
    bounds = AuditReadBounds(max_chunks=3, max_occurrences=4, max_diagnostics=5, max_payloads=6)
    reader = PostgresAuditSnapshotRepository(connection)

    bundle = reader.load_exact_run(RUN_B, "audit/v1", bounds)

    assert bundle.snapshot.run.run_id == RUN_B
    assert connection.commits == 1
    assert connection.rollbacks == 0
    assert connection.cursor_obj.closed
    sql = "\n".join(statement for statement, _ in connection.cursor_obj.statements)
    lowered = sql.lower()
    assert "order by ordinal, chunk_id" in lowered
    assert "order by payload_id, occurrence_ordinal" in lowered
    assert "origin='splitter'" in lowered
    assert "order by diagnostic_id, code" in lowered
    assert "processed_files" not in lowered
    assert "latest" not in lowered and "current" not in lowered
    assert not hasattr(reader, "load_latest") and not hasattr(reader, "load_for_file")
    queries = connection.cursor_obj.statements
    run_scoped = [item for item in queries if "run_id=%s" in item[0]]
    assert run_scoped and all(item[1][0] == RUN_B for item in run_scoped)
    assert any(item[1][-1] == 4 for item in queries if "FROM lore_core.chunks" in item[0])
    assert any(item[1][-1] == 5 for item in queries if "payload_occurrences" in item[0])
    payload_query = next(item for item in queries if "FROM lore_core.payloads" in item[0])
    assert payload_query[1][0] == ["payload-1"]
    assert RUN_B not in payload_query[1]


def test_postgres_reader_canonicalizes_before_cursor_and_fails_missing_or_nonterminal():
    invalid = ScriptedConnection()
    with pytest.raises(AuditRepositoryError) as error:
        PostgresAuditSnapshotRepository(invalid).load_exact_run(
            "not-a-uuid", "audit/v1", AuditReadBounds()
        )
    assert error.value.category == "invalid_request"
    assert invalid.cursor_calls == 0

    for rows in ([], [run_row(status="active", finished_at=None)]):
        connection = scripted_connection(**{"FROM lore_core.processing_runs": rows})
        with pytest.raises(AuditRepositoryError) as error:
            PostgresAuditSnapshotRepository(connection).load_exact_run(
                RUN_B, "audit/v1", AuditReadBounds()
            )
        assert error.value.category in {"snapshot_unavailable", "snapshot_invalid"}
        assert connection.commits == 0
        assert connection.rollbacks == 1
        assert connection.cursor_obj.closed


def test_postgres_reader_detects_bound_plus_one_and_redacts_late_failures():
    overflow = scripted_connection(
        **{"FROM lore_core.payload_occurrences": [occurrence_row(), occurrence_row()]}
    )
    with pytest.raises(AuditRepositoryError) as error:
        PostgresAuditSnapshotRepository(overflow).load_exact_run(
            RUN_B, "audit/v1", AuditReadBounds(max_occurrences=1)
        )
    assert error.value.category == "snapshot_bounds"
    assert overflow.rollbacks == 1

    failed = scripted_connection()
    failed.cursor_obj.fail_on = "FROM lore_core.diagnostics"
    with pytest.raises(AuditRepositoryError) as error:
        PostgresAuditSnapshotRepository(failed).load_exact_run(
            RUN_B, "audit/v1", AuditReadBounds()
        )
    assert error.value.category == "read_failed"
    assert "password" not in str(error.value) and "canary" not in str(error.value)
    assert failed.commits == 0 and failed.rollbacks == 1 and failed.cursor_obj.closed


def _seed_terminal_run(connection, run_id, logical_file_key, suffix):
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO lore_core.processed_files "
            "(logical_file_key, source_id, stream, file_id, status, latest_run_id) "
            "VALUES (%s,%s,'files',%s,'success',%s)",
            (logical_file_key, f"drive-{suffix}", suffix, run_id),
        )
        cursor.execute(
            "INSERT INTO lore_core.processing_runs "
            "(run_id, logical_file_key, source_content_hash, config_hash, operator_version, "
            "chunk_schema_version, status, lease_until, finished_at, payload_count) "
            "VALUES (%s,%s,%s,'config','operator','chunks','success',now(),now(),%s)",
            (run_id, logical_file_key, f"source-{suffix}", 1 if run_id == RUN_B else 0),
        )
    connection.commit()


def _snapshot_database():
    context = ephemeral_postgres()
    connection = context.__enter__()
    apply_migration(connection)
    apply_migration(connection, version="002_chunk_payload_foundation")
    apply_migration(connection, version="004_audit_diagnostics")
    _seed_terminal_run(connection, RUN_A, "drive.files.a", "a")
    _seed_terminal_run(connection, RUN_B, "drive.files.b", "b")
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO lore_core.payloads "
            "(payload_id, logical_file_key, run_id, kind, storage, storage_uri, "
            "metadata, content_hash) "
            "VALUES ('payload-1','drive.files.a',%s,'table','table','payload-1',%s,%s),"
            "('decoy','drive.files.a',%s,'table','table','decoy',%s,%s)",
            (
                RUN_A,
                Jsonb({"audit_registration": registration()}),
                SHA_A,
                RUN_A,
                Jsonb({"audit_registration": {"schema_version": "malformed-decoy"}}),
                "d" * 64,
            ),
        )
        cursor.execute(
            "INSERT INTO lore_core.payload_occurrences "
            "(run_id,payload_id,occurrence_ordinal,kind,storage_identity,content_hash) "
            "VALUES (%s,'payload-1',0,'table','payload-1',%s)",
            (RUN_B, SHA_A),
        )
    connection.commit()
    return context, connection


def test_postgres_reader_accepts_two_run_global_payload_reuse():
    context, connection = _snapshot_database()
    try:
        bundle = PostgresAuditSnapshotRepository(connection).load_exact_run(
            RUN_B, "audit/v1", AuditReadBounds()
        )
        assert [fact.payload_id for fact in bundle.payload_facts] == ["payload-1"]
        assert bundle.payload_facts[0].registered is True
    finally:
        context.__exit__(None, None, None)


def test_postgres_reader_excludes_unreferenced_payload_decoys():
    context, connection = _snapshot_database()
    try:
        bundle = PostgresAuditSnapshotRepository(connection).load_exact_run(
            RUN_B, "audit/v1", AuditReadBounds()
        )
        assert "decoy" not in repr(bundle)
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE lore_core.payload_occurrences SET content_hash=%s "
                "WHERE run_id=%s AND payload_id='payload-1'",
                ("e" * 64, RUN_B),
            )
        connection.commit()
        with pytest.raises(AuditRepositoryError) as error:
            PostgresAuditSnapshotRepository(connection).load_exact_run(
                RUN_B, "audit/v1", AuditReadBounds()
            )
        assert error.value.category == "snapshot_invalid"
    finally:
        context.__exit__(None, None, None)
