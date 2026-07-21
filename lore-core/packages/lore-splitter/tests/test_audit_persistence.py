from __future__ import annotations

from contextlib import contextmanager

import pytest
from psycopg.types.json import Jsonb

from lore_audit.contracts import (
    AUDIT_COMPLETED,
    AUDIT_FAILED,
    AuditLifecycleResult,
    AuditTarget,
    DiagnosticOrigin,
    LifecycleDiagnostic,
    LifecycleOutcome,
    RuleOutcome,
    RuleResult,
    Severity,
)
from lore_audit.engine_contracts import (
    EMPTY_DOMAIN_TARGET_ID,
    AuditEngineResult,
)
from lore_audit.persistence import PostgresAuditResultWriter
from lore_splitter.storage.core_schema import apply_migration
from postgres_test_harness import ephemeral_postgres

RUN_ID = "00000000-0000-0000-0000-000000000021"


def finding(rule_id="chunk_texts", target_id="chunk-1", message="finding"):
    return RuleResult(
        ruleset_version="audit/v1",
        rule_id=rule_id,
        outcome=RuleOutcome.FINDING,
        target=AuditTarget("chunk", target_id),
        severity=Severity.ERROR,
        diagnostic_key=f"audit/v1:chunk:{target_id}:{rule_id}",
        origin=DiagnosticOrigin.AUDIT_RULE,
        message=message,
        details={"ruleset_version": "audit/v1", "defects": [{"code": "bad"}]},
    )


def completed(*results):
    outcome_counts = {outcome: 0 for outcome in RuleOutcome}
    severity_counts = {severity: 0 for severity in Severity}
    for result in results:
        outcome_counts[result.outcome] += 1
        if result.outcome is RuleOutcome.FINDING:
            severity_counts[result.severity] += 1
    lifecycle = AuditLifecycleResult(
        LifecycleOutcome.COMPLETED,
        "audit/v1",
        RUN_ID,
        AUDIT_COMPLETED,
        len(results),
        outcome_counts,
        severity_counts,
        None,
    )
    return AuditEngineResult(tuple(results), lifecycle)


def failed(category="engine_failed", stage="engine"):
    return AuditLifecycleResult(
        LifecycleOutcome.FAILED,
        "audit/v1",
        RUN_ID,
        AUDIT_FAILED,
        None,
        None,
        None,
        LifecycleDiagnostic(
            AUDIT_FAILED,
            "Audit execution failed",
            {"category": category, "stage": stage, "ruleset_version": "audit/v1"},
        ),
    )


class Cursor:
    def __init__(self, *, fail_at=None, run_exists=True, write_affected=True):
        self.statements = []
        self.fail_at = fail_at
        self.run_exists = run_exists
        self.write_affected = write_affected
        self.closed = False

    def execute(self, sql, params=()):
        self.statements.append((" ".join(sql.split()), params))
        if self.fail_at == len(self.statements):
            raise RuntimeError("late database failure")

    def fetchone(self):
        sql = self.statements[-1][0]
        if "FOR KEY SHARE" in sql:
            return (RUN_ID,) if self.run_exists else None
        if "RETURNING" in sql:
            return (1,) if self.write_affected else None
        raise AssertionError(f"unexpected fetchone for {sql}")

    def close(self):
        self.closed = True


class Connection:
    def __init__(self, *, fail_at=None, run_exists=True, write_affected=True):
        self.cursor_obj = Cursor(
            fail_at=fail_at,
            run_exists=run_exists,
            write_affected=write_affected,
        )
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def test_completed_writer_upserts_findings_reconciles_exact_ruleset_and_commits_once():
    connection = Connection()
    writer = PostgresAuditResultWriter(connection)

    writer.write_completed(completed(finding()))

    sql = "\n".join(statement for statement, _ in connection.cursor_obj.statements)
    assert connection.commits == 1
    assert connection.rollbacks == 0
    assert connection.cursor_obj.closed
    assert "ON CONFLICT (run_id, diagnostic_key)" in sql
    assert "DELETE FROM lore_core.diagnostics" in sql
    assert "origin='audit_rule'" in sql
    assert "diagnostic_key LIKE" in sql
    assert "AUDIT_COMPLETED" in repr(connection.cursor_obj.statements)
    assert not any(
        token in sql.upper()
        for token in (
            "UPDATE LORE_CORE.PROCESSING_RUNS",
            "UPDATE LORE_CORE.CHUNKS",
            "UPDATE LORE_CORE.PAYLOADS",
            "UPDATE LORE_CORE.PAYLOAD_OCCURRENCES",
        )
    )


def test_clean_completed_writer_still_reconciles_and_writes_lifecycle():
    connection = Connection()

    PostgresAuditResultWriter(connection).write_completed(completed())

    assert len(connection.cursor_obj.statements) == 3
    assert "FOR KEY SHARE" in connection.cursor_obj.statements[0][0]
    assert "DELETE FROM lore_core.diagnostics" in connection.cursor_obj.statements[1][0]
    assert "AUDIT_COMPLETED" in repr(connection.cursor_obj.statements[2])


def test_completed_late_failure_rolls_back_without_commit():
    connection = Connection(fail_at=3)

    with pytest.raises(RuntimeError, match="late database failure"):
        PostgresAuditResultWriter(connection).write_completed(completed(finding()))

    assert connection.commits == 0
    assert connection.rollbacks == 1
    assert connection.cursor_obj.closed


def test_failed_lifecycle_uses_one_fresh_audit_only_transaction():
    connection = Connection()

    PostgresAuditResultWriter(connection).write_failed(failed())

    assert connection.commits == 1
    assert connection.rollbacks == 0
    assert len(connection.cursor_obj.statements) == 2
    assert "FOR KEY SHARE" in connection.cursor_obj.statements[0][0]
    sql, params = connection.cursor_obj.statements[1]
    assert "ON CONFLICT (run_id, diagnostic_key)" in sql
    assert "AUDIT_FAILED" in repr(params)
    assert params[3].obj["diagnostic"]["details"]["category"] == "engine_failed"


@pytest.mark.parametrize("write", ["completed", "failed"])
def test_lifecycle_writer_rejects_missing_exact_run_without_commit(write):
    connection = Connection(run_exists=False)
    writer = PostgresAuditResultWriter(connection)

    with pytest.raises(RuntimeError, match="audit processing run does not exist"):
        getattr(writer, f"write_{write}")(completed() if write == "completed" else failed())

    assert connection.commits == 0
    assert connection.rollbacks == 1
    assert connection.cursor_obj.closed


@pytest.mark.parametrize("write", ["completed", "failed"])
def test_lifecycle_writer_requires_one_affected_diagnostic_row(write):
    connection = Connection(write_affected=False)
    writer = PostgresAuditResultWriter(connection)

    with pytest.raises(RuntimeError, match="audit diagnostic write affected no rows"):
        getattr(writer, f"write_{write}")(completed() if write == "completed" else failed())

    assert connection.commits == 0
    assert connection.rollbacks == 1


def _seed_processing_evidence(connection):
    apply_migration(connection)
    apply_migration(connection, version="002_chunk_payload_foundation")
    apply_migration(connection, version="004_audit_diagnostics")
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO lore_core.processed_files "
            "(logical_file_key,source_id,stream,file_id,status,latest_run_id) "
            "VALUES ('drive.files.audit','drive','files','audit','success',%s)",
            (RUN_ID,),
        )
        cursor.execute(
            "INSERT INTO lore_core.processing_runs "
            "(run_id,logical_file_key,source_content_hash,config_hash,operator_version,"
            "chunk_schema_version,status,lease_until,finished_at,chunk_count,payload_count,"
            "warning_count) "
            "VALUES (%s,'drive.files.audit','source','config','operator','chunks','success',"
            "now(),now(),1,1,1)",
            (RUN_ID,),
        )
        cursor.execute(
            "INSERT INTO lore_core.chunks "
            "(chunk_id,logical_file_key,run_id,ordinal,pipeline_type,chunk_type,vector_text,"
            "fulltext,display_text,content_signature,vector_text_hash,fulltext_hash) "
            "VALUES ('chunk-1','drive.files.audit',%s,0,'document','text','v','f','d','c','v','f')",
            (RUN_ID,),
        )
        cursor.execute(
            "INSERT INTO lore_core.payloads "
            "(payload_id,logical_file_key,run_id,kind,storage,storage_uri,content_hash) "
            "VALUES ('payload-1','drive.files.audit',%s,'table','table','payload-1','hash')",
            (RUN_ID,),
        )
        cursor.execute(
            "INSERT INTO lore_core.payload_occurrences "
            "(run_id,payload_id,occurrence_ordinal,kind,storage_identity,content_hash) "
            "VALUES (%s,'payload-1',0,'table','payload-1','hash')",
            (RUN_ID,),
        )
        cursor.execute(
            "INSERT INTO lore_core.diagnostics "
            "(logical_file_key,run_id,level,code,message,stage,details,origin) "
            "VALUES ('drive.files.audit',%s,'warning','SOURCE','source','splitter',%s,'splitter')",
            (RUN_ID, Jsonb({"stable": True})),
        )
        cursor.execute(
            "INSERT INTO lore_core.diagnostics "
            "(logical_file_key,run_id,level,code,message,stage,details,origin,diagnostic_key) "
            "VALUES ('drive.files.audit',%s,'warning','OTHER','other','audit',%s,'audit_rule',"
            "'audit/v2:run:other:rule')",
            (RUN_ID, Jsonb({"ruleset_version": "audit/v2"})),
        )
    connection.commit()


def _processing_bytes(connection):
    queries = (
        "SELECT row_to_json(t)::text FROM (SELECT * FROM lore_core.processing_runs WHERE run_id=%s) t",
        "SELECT row_to_json(t)::text FROM (SELECT * FROM lore_core.chunks WHERE run_id=%s) t",
        "SELECT row_to_json(t)::text FROM (SELECT * FROM lore_core.payloads WHERE run_id=%s) t",
        "SELECT row_to_json(t)::text FROM (SELECT * FROM lore_core.payload_occurrences WHERE run_id=%s) t",
        "SELECT row_to_json(t)::text FROM (SELECT * FROM lore_core.diagnostics "
        "WHERE run_id=%s AND origin='splitter') t",
    )
    with connection.cursor() as cursor:
        values = []
        for query in queries:
            cursor.execute(query, (RUN_ID,))
            values.append(tuple(row[0] for row in cursor.fetchall()))
    connection.rollback()
    return tuple(values)


@contextmanager
def audit_database():
    with ephemeral_postgres() as connection:
        _seed_processing_evidence(connection)
        yield connection


def test_postgres_retry_reconciliation_and_processing_immutability():
    with audit_database() as connection:
        before = _processing_bytes(connection)
        writer = PostgresAuditResultWriter(connection)
        writer.write_completed(completed(finding(message="first")))
        writer.write_completed(completed(finding(message="changed")))
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT message FROM lore_core.diagnostics WHERE run_id=%s "
                "AND diagnostic_key='audit/v1:chunk:chunk-1:chunk_texts'",
                (RUN_ID,),
            )
            assert cursor.fetchone()[0] == "changed"
        writer.write_completed(completed())
        writer.write_failed(failed())

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT diagnostic_key,code,message,details FROM lore_core.diagnostics "
                "WHERE run_id=%s AND origin='audit_rule' ORDER BY diagnostic_key",
                (RUN_ID,),
            )
            rows = cursor.fetchall()
        assert [row[0] for row in rows] == [
            "audit/v1:lifecycle:AUDIT_COMPLETED",
            "audit/v1:lifecycle:AUDIT_FAILED",
            "audit/v2:run:other:rule",
        ]
        assert rows[0][3]["checked_rule_count"] == 0
        assert _processing_bytes(connection) == before


def test_postgres_empty_domain_finding_persists_without_foreign_target():
    with audit_database() as connection:
        aggregate = finding(
            rule_id="vector_hard_limit",
            target_id=EMPTY_DOMAIN_TARGET_ID,
        )

        PostgresAuditResultWriter(connection).write_completed(completed(aggregate))

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT chunk_id,payload_id,details->'target'->>'target_id' "
                "FROM lore_core.diagnostics WHERE run_id=%s AND diagnostic_key=%s",
                (RUN_ID, aggregate.diagnostic_key),
            )
            row = cursor.fetchone()
        assert row == (None, None, EMPTY_DOMAIN_TARGET_ID)


def test_postgres_completed_late_failure_rolls_back_findings_and_reconciliation():
    with audit_database() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO lore_core.diagnostics "
                "(logical_file_key,run_id,level,code,message,stage,details,origin,diagnostic_key) "
                "VALUES ('drive.files.audit',%s,'error','old','old','audit',%s,'audit_rule',"
                "'audit/v1:chunk:chunk-1:chunk_type')",
                (RUN_ID, Jsonb({"ruleset_version": "audit/v1"})),
            )
            cursor.execute(
                "CREATE FUNCTION fail_audit_completed() RETURNS trigger LANGUAGE plpgsql AS $$ "
                "BEGIN IF NEW.code='AUDIT_COMPLETED' THEN RAISE EXCEPTION 'late'; END IF; "
                "RETURN NEW; END $$"
            )
            cursor.execute(
                "CREATE TRIGGER fail_audit_completed BEFORE INSERT OR UPDATE "
                "ON lore_core.diagnostics FOR EACH ROW EXECUTE FUNCTION fail_audit_completed()"
            )
        connection.commit()

        with pytest.raises(Exception, match="late"):
            PostgresAuditResultWriter(connection).write_completed(completed(finding()))

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT diagnostic_key FROM lore_core.diagnostics WHERE run_id=%s "
                "AND origin='audit_rule' ORDER BY diagnostic_key",
                (RUN_ID,),
            )
            assert [row[0] for row in cursor.fetchall()] == [
                "audit/v1:chunk:chunk-1:chunk_type",
                "audit/v2:run:other:rule",
            ]


@pytest.mark.parametrize("write", ["completed", "failed"])
def test_postgres_lifecycle_writer_rejects_run_deleted_after_snapshot_read(write):
    with audit_database() as connection:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM lore_core.diagnostics WHERE run_id=%s", (RUN_ID,))
            cursor.execute("DELETE FROM lore_core.payload_occurrences WHERE run_id=%s", (RUN_ID,))
            cursor.execute("DELETE FROM lore_core.payloads WHERE run_id=%s", (RUN_ID,))
            cursor.execute("DELETE FROM lore_core.chunks WHERE run_id=%s", (RUN_ID,))
            cursor.execute(
                "UPDATE lore_core.processed_files SET latest_run_id=NULL WHERE latest_run_id=%s",
                (RUN_ID,),
            )
            cursor.execute("DELETE FROM lore_core.processing_runs WHERE run_id=%s", (RUN_ID,))
        connection.commit()

        writer = PostgresAuditResultWriter(connection)
        with pytest.raises(RuntimeError, match="audit processing run does not exist"):
            getattr(writer, f"write_{write}")(
                completed() if write == "completed" else failed()
            )

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM lore_core.diagnostics WHERE run_id=%s AND origin='audit_rule'",
                (RUN_ID,),
            )
            assert cursor.fetchone()[0] == 0


@pytest.mark.skip(
    reason="Phase-3 Airflow path: requires airflow_adapters (build_airflow_audit_adapters, "
    "PostgresHook, S3Hook) which are not available in lore-splitter. "
    "Re-enable in Phase 3 when airflow hooks are wired."
)
def test_real_postgres_catalog_error_does_not_poison_failure_write():
    pass
