from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest
from psycopg.types.json import Jsonb

from lore_splitter.contracts import SourceFile
from lore_splitter.per_file import (
    Diagnostic,
    ProcessingAlreadyActive,
    RunResult,
    RunStatus,
    build_processing_identity,
)
from lore_splitter.storage.core_repository import CoreRepository
from lore_splitter.storage.core_schema import apply_migration, migration_sql
from postgres_test_harness import ephemeral_postgres

OLD_RUN_ID = "00000000-0000-0000-0000-000000000001"
NEW_RUN_ID = "00000000-0000-0000-0000-000000000002"
SHA_A = "a" * 64


def registration(row_count=1):
    return {
        "schema_version": "audit/payload-registration/v1",
        "payload_id": "payload-1",
        "kind": "table",
        "backend": "postgres",
        "registration_identity": {
            "schema_name": "lore_toast",
            "table_name": "toast_payload_1",
            "row_count": row_count,
        },
        "metadata": {"row_count": row_count},
        "summary": {"row_count": row_count},
    }


def registration_with_lineage(source_checksum: str, source_location: dict):
    value = registration()
    lineage = {
        "source_kind": "workbook",
        "source_checksum": source_checksum,
        "source_location": source_location,
    }
    value["registration_identity"].update(lineage)
    value["metadata"].update(
        {
            **lineage,
            "sheet": {"name": source_location["sheet"], "index": 0},
            "range": {"a1": source_location["range"]},
        }
    )
    return value


def image_registration():
    return {
        "schema_version": "audit/payload-registration/v1",
        "payload_id": "payload-1",
        "kind": "image",
        "backend": "s3",
        "registration_identity": {
            "bucket": "lore-images",
            "object_key": "toast/payload-1.png",
            "content_type": "image/png",
            "extension": ".png",
            "byte_size": 12,
            "checksum_sha256": SHA_A,
        },
        "metadata": {
            "content_type": "image/png",
            "extension": ".png",
            "byte_size": 12,
            "checksum_sha256": SHA_A,
        },
        "summary": {},
    }


def persisted_payload(**overrides):
    value = {
        "verified": True,
        "payload_id": "payload-1",
        "occurrence_ordinal": 0,
        "kind": "table",
        "storage_identity": "payload-1",
        "content_hash": SHA_A,
        "coordinates": {"range": "A1:B2"},
        "metadata": {"candidate": "second", "audit_registration": registration()},
    }
    value.update(overrides)
    return value


def seed_run(connection, run_id, logical_file_key, suffix):
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO lore_core.processed_files "
            "(logical_file_key, source_id, stream, file_id, status, latest_run_id) "
            "VALUES (%s,%s,'files',%s,'active',%s)",
            (logical_file_key, f"drive-{suffix}", suffix, run_id),
        )
        cursor.execute(
            "INSERT INTO lore_core.processing_runs "
            "(run_id, logical_file_key, source_content_hash, config_hash, operator_version, "
            "chunk_schema_version, status, lease_until) "
            "VALUES (%s,%s,%s,'config','operator','chunks','active',now() + interval '1 hour')",
            (run_id, logical_file_key, f"source-{suffix}"),
        )
    connection.commit()


@contextmanager
def registration_database(*, existing_metadata=None):
    with ephemeral_postgres() as connection:
        apply_migration(connection)
        apply_migration(connection, version="002_chunk_payload_foundation")
        seed_run(connection, NEW_RUN_ID, "drive:files:new", "new")
        if existing_metadata is not None:
            seed_run(connection, OLD_RUN_ID, "drive:files:old", "old")
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO lore_core.payloads "
                    "(payload_id, logical_file_key, run_id, kind, storage, storage_uri, "
                    "coordinates, metadata, content_hash) "
                    "VALUES ('payload-1','drive:files:old',%s,'table','table','payload-1',%s,%s,%s)",
                    (
                        OLD_RUN_ID,
                        Jsonb({"owner_coordinate": 7}),
                        Jsonb(existing_metadata),
                        SHA_A,
                    ),
                )
            connection.commit()
        yield connection


def finalize_registered_payload(connection, payload=None):
    return CoreRepository(connection).finalize_persisted(
        NEW_RUN_ID,
        logical_file_key="drive:files:new",
        chunks=[],
        payloads=[payload or persisted_payload()],
        diagnostics=[],
        counts={"chunk_count": 0, "payload_count": 1},
    )


class Cursor:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.statements = []
        self.closed = False

    def execute(self, sql, params=()):
        self.statements.append((sql, params))

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def close(self):
        self.closed = True


class Connection:
    def __init__(self, rows=()):
        self.cursor_obj = Cursor(rows)
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def source():
    return SourceFile(
        "drive",
        "files",
        "42",
        "docs/a.md",
        "docs/a.md",
        "text/markdown",
        3,
        metadata={"secret": "hidden"},
    )


def identity():
    return build_processing_identity(
        source(), "sha", {"limit": 1}, operator_version="op/1", chunk_schema_version="chunk/1"
    )


def diagnostic_insert_columns(sql: str) -> tuple[str, ...]:
    prefix, separator, remainder = sql.partition("INSERT INTO lore_core.diagnostics (")
    assert not prefix and separator
    columns, separator, _ = remainder.partition(")")
    assert separator
    return tuple(column.strip() for column in columns.split(","))


def test_claim_inserts_active_run_and_sanitized_snapshot():
    connection = Connection()
    run_id = CoreRepository(connection).claim(
        source(), identity(), now=datetime(2026, 1, 1, tzinfo=UTC)
    )
    assert isinstance(run_id, str)
    assert connection.commits == 1
    assert len(connection.cursor_obj.statements) == 4
    assert "INSERT INTO lore_core.processed_files" in connection.cursor_obj.statements[2][0]
    assert "INSERT INTO lore_core.processing_runs" in connection.cursor_obj.statements[3][0]
    assert isinstance(connection.cursor_obj.statements[2][1][13], Jsonb)
    assert isinstance(connection.cursor_obj.statements[2][1][14], Jsonb)
    assert all("hidden" not in str(statement) for statement in connection.cursor_obj.statements)


def test_claim_rejects_active_lease_and_rolls_back():
    now = datetime(2026, 1, 1, tzinfo=UTC)
    connection = Connection([(None,), ("run-1", "active", now, now + timedelta(minutes=5), None)])
    with pytest.raises(ProcessingAlreadyActive):
        CoreRepository(connection).claim(source(), identity(), now=now)
    assert connection.rollbacks == 1


def test_cache_hit_returns_existing_result_without_run_insert():
    now = datetime(2026, 1, 1, tzinfo=UTC)
    connection = Connection([("run-1",), ("run-1", "success", now, now, "run-1")])
    result = CoreRepository(connection).claim(source(), identity(), now=now)
    assert isinstance(result, RunResult)
    assert result.reused and result.status is RunStatus.SUCCESS
    assert len(connection.cursor_obj.statements) == 3
    assert isinstance(connection.cursor_obj.statements[-1][1][2], Jsonb)
    assert isinstance(connection.cursor_obj.statements[-1][1][3], Jsonb)


def test_changed_content_claim_supersedes_current_success_and_updates_snapshot():
    connection = Connection([("old-run",),])
    run_id = CoreRepository(connection).claim(
        source(), identity(), now=datetime(2026, 1, 1, tzinfo=UTC)
    )
    assert isinstance(run_id, str)
    insert = connection.cursor_obj.statements[-1]
    assert "source_content_hash" in insert[0]
    assert "old-run" in insert[1]


def test_claim_reads_current_success_only_from_processed_files():
    connection = Connection()
    CoreRepository(connection).claim(source(), identity(), now=datetime(2026, 1, 1, tzinfo=UTC))

    snapshot_query, claim_query = (
        statement[0] for statement in connection.cursor_obj.statements[:2]
    )
    assert "FROM lore_core.processed_files" in snapshot_query
    assert "current_success_run_id" in snapshot_query
    assert "current_success_run_id" not in claim_query


def test_finalization_receives_logical_key_outside_public_chunk_contract():
    connection = Connection([("payload-1",), ("drive:files:42", None)])
    CoreRepository(connection).finalize_persisted(
        "run-1",
        logical_file_key="drive:files:42",
        chunks=[
            {
                "chunk_id": "chunk-1",
                "ordinal": 0,
                "pipeline_type": "markdown",
                "chunk_type": "text",
                "vector_text": "v",
                "fulltext": "f",
                "display_text": "d",
                "content_signature": "signature",
                "vector_hash": "vector",
                "fulltext_hash": "full",
            }
        ],
        payloads=[
            {
                "verified": True,
                "payload_id": "payload-1",
                "occurrence_ordinal": 0,
                "kind": "table",
                "storage_identity": "lore_toast.payload_1",
                "content_hash": "a" * 64,
                "metadata": {"audit_registration": registration()},
            }
        ],
        diagnostics=[],
        counts={"chunk_count": 1, "payload_count": 1},
    )

    sql = "\n".join(statement[0] for statement in connection.cursor_obj.statements)
    assert "INSERT INTO lore_core.payloads" in sql
    assert "drive:files:42" in str(connection.cursor_obj.statements)
    assert connection.commits == 1


def test_finalization_rolls_back_core_rows_when_terminal_update_fails():
    class FailingCursor(Cursor):
        def execute(self, sql, params=()):
            super().execute(sql, params)
            if "UPDATE lore_core.processing_runs SET status" in sql:
                raise RuntimeError("terminal update failed")

    connection = Connection()
    connection.cursor_obj = FailingCursor()
    with pytest.raises(RuntimeError, match="terminal update failed"):
        CoreRepository(connection).finalize_persisted(
            "run-1",
            logical_file_key="drive:files:42",
            chunks=[],
            payloads=[],
            diagnostics=[],
            counts={},
        )
    assert connection.commits == 0
    assert connection.rollbacks == 1


def test_add_diagnostic_omits_audit_identity_and_uses_database_splitter_default():
    connection = Connection()
    CoreRepository(connection).add_diagnostic(
        "drive:files:42",
        Diagnostic(
            level="warning",
            code="PROCESSING_WARNING",
            message="processing warning",
            stage="extract",
            details={"row": 3},
        ),
        run_id="run-1",
    )

    sql, params = connection.cursor_obj.statements[0]
    assert diagnostic_insert_columns(sql) == (
        "logical_file_key",
        "run_id",
        "level",
        "code",
        "message",
        "stage",
        "details",
    )
    assert "origin" not in sql and "diagnostic_key" not in sql
    assert sql.count("%s") == len(params) == 7
    assert "DEFAULT 'splitter'" in migration_sql("004_audit_diagnostics")
    assert connection.commits == 1
    assert connection.rollbacks == 0
    assert connection.cursor_obj.closed


def test_finalize_persisted_registers_fresh_payload_in_postgres():
    with registration_database() as connection:
        finalize_registered_payload(connection)

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT logical_file_key, run_id::text, kind, storage, storage_uri, metadata "
                "FROM lore_core.payloads WHERE payload_id='payload-1'"
            )
            row = cursor.fetchone()

    assert row[:5] == (
        "drive:files:new",
        NEW_RUN_ID,
        "table",
        "table",
        "payload-1",
    )
    assert row[5] == {
        "candidate": "second",
        "audit_registration": registration(),
    }


def test_finalize_persisted_reuses_identical_registered_payload():
    original_metadata = {
        "first_owner": {"retained": True},
        "audit_registration": registration(),
    }
    with registration_database(existing_metadata=original_metadata) as connection:
        finalize_registered_payload(connection)

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT logical_file_key, run_id::text, coordinates, metadata "
                "FROM lore_core.payloads WHERE payload_id='payload-1'"
            )
            row = cursor.fetchone()

    assert row == (
        "drive:files:old",
        OLD_RUN_ID,
        {"owner_coordinate": 7},
        original_metadata,
    )


def test_finalize_persisted_reuses_registration_with_different_lineage():
    original_registration = registration_with_lineage(
        "1" * 64,
        {"sheet": "Original", "range": "A1:B2"},
    )
    candidate_registration = registration_with_lineage(
        "2" * 64,
        {"sheet": "Duplicate", "range": "D4:E5"},
    )
    original_metadata = {
        "first_owner": {"retained": True},
        "audit_registration": original_registration,
    }
    candidate = persisted_payload(
        metadata={
            "candidate": "second",
            "audit_registration": candidate_registration,
        },
        occurrence_metadata={"source_checksum": "2" * 64},
    )

    with registration_database(existing_metadata=original_metadata) as connection:
        finalize_registered_payload(connection, candidate)

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT logical_file_key, run_id::text, coordinates, metadata "
                "FROM lore_core.payloads WHERE payload_id='payload-1'"
            )
            payload_row = cursor.fetchone()
            cursor.execute(
                "SELECT metadata FROM lore_core.payload_occurrences "
                "WHERE run_id=%s AND payload_id='payload-1'",
                (NEW_RUN_ID,),
            )
            occurrence_metadata = cursor.fetchone()[0]

    assert payload_row == (
        "drive:files:old",
        OLD_RUN_ID,
        {"owner_coordinate": 7},
        original_metadata,
    )
    assert occurrence_metadata == {"source_checksum": "2" * 64}


def test_finalize_persisted_installs_registration_on_legacy_payload():
    original_metadata = {"first_owner": {"retained": True}, "legacy": "untouched"}
    with registration_database(existing_metadata=original_metadata) as connection:
        finalize_registered_payload(connection)

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT logical_file_key, run_id::text, coordinates, metadata "
                "FROM lore_core.payloads WHERE payload_id='payload-1'"
            )
            row = cursor.fetchone()

    assert row[:3] == ("drive:files:old", OLD_RUN_ID, {"owner_coordinate": 7})
    assert row[3] == {**original_metadata, "audit_registration": registration()}
    assert "candidate" not in row[3]


def test_finalize_persisted_rejects_conflicting_payload_registration():
    original_metadata = {
        "first_owner": {"retained": True},
        "audit_registration": registration(),
    }
    candidates = []
    conflicting_registration = persisted_payload()
    conflicting_registration["metadata"] = {
        "audit_registration": registration(row_count=2)
    }
    candidates.append(conflicting_registration)
    candidates.append(
        persisted_payload(
            kind="image",
            metadata={"audit_registration": image_registration()},
        )
    )
    candidates.append(persisted_payload(storage_identity="other-payload"))
    candidates.append(persisted_payload(content_hash="b" * 64))

    with registration_database(existing_metadata=original_metadata) as connection:
        for candidate in candidates:
            with pytest.raises(ValueError, match="^payload registration conflict$"):
                finalize_registered_payload(connection, deepcopy(candidate))

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT logical_file_key, run_id::text, coordinates, metadata "
                "FROM lore_core.payloads WHERE payload_id='payload-1'"
            )
            payload_row = cursor.fetchone()
            cursor.execute(
                "SELECT count(*) FROM lore_core.payload_occurrences WHERE run_id=%s",
                (NEW_RUN_ID,),
            )
            occurrence_count = cursor.fetchone()[0]
            cursor.execute(
                "SELECT status FROM lore_core.processing_runs WHERE run_id=%s", (NEW_RUN_ID,)
            )
            run_status = cursor.fetchone()[0]

    assert payload_row == (
        "drive:files:old",
        OLD_RUN_ID,
        {"owner_coordinate": 7},
        original_metadata,
    )
    assert occurrence_count == 0
    assert run_status == "active"


def test_finalize_persisted_diagnostic_omits_audit_identity_in_one_transaction():
    connection = Connection([("drive:files:42", None)])
    CoreRepository(connection).finalize_persisted(
        "run-1",
        logical_file_key="drive:files:42",
        chunks=[],
        payloads=[],
        diagnostics=[
            Diagnostic(
                level="error",
                code="PROCESSING_ERROR",
                message="processing error",
                stage="persist",
                details={"attempt": 1},
            )
        ],
        counts={"error_count": 1},
    )

    diagnostic_statements = [
        statement
        for statement in connection.cursor_obj.statements
        if statement[0].startswith("INSERT INTO lore_core.diagnostics")
    ]
    assert len(diagnostic_statements) == 1
    sql, params = diagnostic_statements[0]
    assert diagnostic_insert_columns(sql) == (
        "logical_file_key",
        "run_id",
        "level",
        "code",
        "message",
        "stage",
        "details",
    )
    assert "origin" not in sql and "diagnostic_key" not in sql
    assert "SELECT logical_file_key" in sql
    assert sql.count("%s") == len(params) == 7
    assert "DEFAULT 'splitter'" in migration_sql("004_audit_diagnostics")
    assert connection.commits == 1
    assert connection.rollbacks == 0
    assert connection.cursor_obj.closed
