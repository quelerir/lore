"""Phase 26 real provider and disposable-PostgreSQL acceptance composition."""

from __future__ import annotations

import pytest

pytest.importorskip("airflow.models.dagbag", reason="Phase-3 UAT needs a real Airflow install")

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from airflow.exceptions import AirflowFailException
from airflow.models.dagbag import DagBag
from lore_audit.persistence import PostgresAuditResultWriter
from lore_audit.snapshot_repository import (
    AuditReadBounds,
    PostgresAuditSnapshotRepository,
)
from airflow.providers.lore.operators.lore_splitter_audit_operator import (
    LoreSplitterAuditOperator,
)
from lore_splitter.storage.core_schema import apply_migration
from psycopg.types.json import Jsonb

from postgres_test_harness import ephemeral_postgres

PROVIDER_ROOT = Path(__file__).resolve().parents[1]
DAG_PATH = PROVIDER_ROOT / "example_dags" / "lore_splitter.py"
CONFIG_PATH = PROVIDER_ROOT / "example_dags" / "configs" / "lore.yaml.example"
FILE_KEY = "drive.files.phase26-overlap"
RUN_A = "00000000-0000-0000-0000-000000000260"
RUN_B = "00000000-0000-0000-0000-000000000261"
REPRESENTATIVE_RUNS = (
    ("document", "00000000-0000-0000-0000-000000000262", "document", "success"),
    ("workbook", "00000000-0000-0000-0000-000000000263", "spreadsheet", "success"),
    ("presentation", "00000000-0000-0000-0000-000000000264", "document", "success"),
    ("transcript", "00000000-0000-0000-0000-000000000265", "transcript", "success"),
    ("failed", "00000000-0000-0000-0000-000000000266", "document", "failed"),
    ("skipped", "00000000-0000-0000-0000-000000000267", "document", "skipped"),
)


class ClaimTaskInstance:
    def __init__(self, map_index: int, run_id: str) -> None:
        self.map_index = map_index
        self.run_id = run_id
        self.pulls: list[dict[str, object]] = []

    def xcom_pull(self, **kwargs):
        self.pulls.append(kwargs)
        return {"schema_version": "lore/run-claim/v1", "run_id": self.run_id}


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _apply_all_migrations(connection) -> None:
    for version in (
        "001_lore_core",
        "002_chunk_payload_foundation",
        "003_orchestration_claim_key",
        "004_audit_diagnostics",
    ):
        apply_migration(connection, version=version)


def _seed_overlapping_runs(connection) -> None:
    _apply_all_migrations(connection)
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO lore_core.processed_files "
            "(logical_file_key,source_id,stream,file_id,status,latest_run_id) "
            "VALUES (%s,'drive','files','phase26-overlap','success',%s)",
            (FILE_KEY, RUN_A),
        )
        for run_id, source_hash in ((RUN_A, "a" * 64), (RUN_B, "b" * 64)):
            cursor.execute(
                "INSERT INTO lore_core.processing_runs "
                "(run_id,logical_file_key,source_content_hash,config_hash,operator_version,"
                "chunk_schema_version,status,claimed_at,lease_until,finished_at,chunk_count,"
                "payload_count,warning_count,error_count) VALUES "
                "(%s,%s,%s,'config','operator','chunk/v1','success',now(),now(),now(),1,0,0,0)",
                (run_id, FILE_KEY, source_hash),
            )
        rows = (
            (RUN_A, "chunk-run-a", "", "", "", "bad-vector", "bad-full"),
            (
                RUN_B,
                "chunk-run-b",
                "bounded vector text",
                "bounded full text",
                "bounded display text",
                _sha("bounded vector text"),
                _sha("bounded full text"),
            ),
        )
        for run_id, chunk_id, vector, fulltext, display, vector_hash, fulltext_hash in rows:
            cursor.execute(
                "INSERT INTO lore_core.chunks "
                "(chunk_id,logical_file_key,run_id,ordinal,pipeline_type,chunk_type,vector_text,"
                "fulltext,display_text,coordinates,metadata,payload_refs,content_signature,"
                "vector_text_hash,fulltext_hash) VALUES "
                "(%s,%s,%s,0,'document','text',%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    chunk_id,
                    FILE_KEY,
                    run_id,
                    vector,
                    fulltext,
                    display,
                    Jsonb({"page": 1}),
                    Jsonb({}),
                    Jsonb([]),
                    f"signature-{chunk_id}",
                    vector_hash,
                    fulltext_hash,
                ),
            )
    connection.commit()


def _operator(connection) -> LoreSplitterAuditOperator:
    def adapter_factory(**kwargs):
        bounds = kwargs["bounds"]
        return SimpleNamespace(
            reader=PostgresAuditSnapshotRepository(connection),
            writer=PostgresAuditResultWriter(connection),
            payload_resolver=None,
            bounds=bounds,
        )

    return LoreSplitterAuditOperator(
        task_id="phase26_audit_file",
        file_item={"file_id": "misleading-latest-run", "run_id": RUN_B},
        splitter_task_id="split_file",
        postgres_conn_id="disposable-postgres",
        s3_conn_id="unused-s3",
        audit_bounds=AuditReadBounds(),
        adapter_factory=adapter_factory,
    )


def _audit_keys(connection, run_id: str) -> tuple[str, ...]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT diagnostic_key FROM lore_core.diagnostics "
            "WHERE run_id=%s AND origin='audit_rule' AND diagnostic_key LIKE 'audit/v1:%%' "
            "ORDER BY diagnostic_key",
            (run_id,),
        )
        rows = tuple(row[0] for row in cursor.fetchall())
    connection.rollback()
    return rows


def _seed_representative_runs(connection) -> None:
    _apply_all_migrations(connection)
    with connection.cursor() as cursor:
        for scenario, run_id, pipeline_type, status in REPRESENTATIVE_RUNS:
            logical_key = f"drive.files.phase26-{scenario}"
            cursor.execute(
                "INSERT INTO lore_core.processed_files "
                "(logical_file_key,source_id,stream,file_id,pipeline_type,status,latest_run_id) "
                "VALUES (%s,'drive','files',%s,%s,%s,%s)",
                (logical_key, f"phase26-{scenario}", pipeline_type, status, run_id),
            )
            terminal_diagnostic = status in {"failed", "skipped"}
            payload_count = 1 if scenario in {"workbook", "presentation"} else 0
            chunk_count = 0 if terminal_diagnostic else 1
            warning_count = 1 if status == "skipped" else 0
            error_count = 1 if status == "failed" else 0
            cursor.execute(
                "INSERT INTO lore_core.processing_runs "
                "(run_id,logical_file_key,source_content_hash,config_hash,operator_version,"
                "chunk_schema_version,status,claimed_at,lease_until,finished_at,chunk_count,"
                "payload_count,warning_count,error_count) VALUES "
                "(%s,%s,%s,'config','operator','chunk/v1',%s,now(),now(),now(),%s,%s,%s,%s)",
                (
                    run_id,
                    logical_key,
                    _sha(f"source-{scenario}"),
                    status,
                    chunk_count,
                    payload_count,
                    warning_count,
                    error_count,
                ),
            )
            if terminal_diagnostic:
                level = "error" if status == "failed" else "warning"
                cursor.execute(
                    "INSERT INTO lore_core.diagnostics "
                    "(logical_file_key,run_id,level,code,message,stage,details,origin) "
                    "VALUES (%s,%s,%s,%s,'bounded terminal evidence','splitter',%s,'splitter')",
                    (logical_key, run_id, level, f"PROCESSING_{status.upper()}", Jsonb({})),
                )
                continue

            payload_id = None
            payload_kind = None
            if scenario == "workbook":
                payload_id, payload_kind = "table-phase26-workbook", "table"
            elif scenario == "presentation":
                payload_id, payload_kind = "image-phase26-presentation", "image"
            payload_refs = []
            if payload_id is not None and payload_kind is not None:
                content_hash = _sha(f"payload-{scenario}")
                payload_refs = [
                    {
                        "payload_id": payload_id,
                        "kind": payload_kind,
                        "occurrence_ordinal": 0,
                    }
                ]
                cursor.execute(
                    "INSERT INTO lore_core.payloads "
                    "(payload_id,logical_file_key,run_id,kind,storage,storage_uri,metadata,"
                    "content_hash) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        payload_id,
                        logical_key,
                        run_id,
                        payload_kind,
                        payload_kind,
                        payload_id,
                        Jsonb({}),
                        content_hash,
                    ),
                )
                cursor.execute(
                    "INSERT INTO lore_core.payload_occurrences "
                    "(run_id,payload_id,occurrence_ordinal,kind,storage_identity,content_hash,"
                    "coordinates,metadata) VALUES (%s,%s,0,%s,%s,%s,%s,%s)",
                    (
                        run_id,
                        payload_id,
                        payload_kind,
                        payload_id,
                        content_hash,
                        Jsonb({"page": 1}),
                        Jsonb({}),
                    ),
                )

            vector_text = f"{scenario} vector text"
            fulltext = f"{scenario} full text"
            coordinates = (
                {"start_ms": 0, "end_ms": 1000}
                if scenario == "transcript"
                else {"page": 1}
            )
            metadata = {"speakers": ["speaker-1"]} if scenario == "transcript" else {}
            cursor.execute(
                "INSERT INTO lore_core.chunks "
                "(chunk_id,logical_file_key,run_id,ordinal,pipeline_type,chunk_type,vector_text,"
                "fulltext,display_text,coordinates,metadata,payload_refs,content_signature,"
                "vector_text_hash,fulltext_hash) VALUES "
                "(%s,%s,%s,0,%s,'text',%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    f"chunk-phase26-{scenario}",
                    logical_key,
                    run_id,
                    pipeline_type,
                    vector_text,
                    fulltext,
                    fulltext,
                    Jsonb(coordinates),
                    Jsonb(metadata),
                    Jsonb(payload_refs),
                    f"signature-{scenario}",
                    _sha(vector_text),
                    _sha(fulltext),
                ),
            )
    connection.commit()


def _processing_snapshot_bytes(connection) -> tuple[tuple[str, ...], ...]:
    queries = (
        "SELECT row_to_json(t)::text FROM (SELECT * FROM lore_core.processed_files "
        "WHERE file_id LIKE 'phase26-%%' ORDER BY logical_file_key) t",
        "SELECT row_to_json(t)::text FROM (SELECT * FROM lore_core.processing_runs "
        "WHERE logical_file_key LIKE 'drive.files.phase26-%%' ORDER BY run_id) t",
        "SELECT row_to_json(t)::text FROM (SELECT * FROM lore_core.chunks "
        "WHERE logical_file_key LIKE 'drive.files.phase26-%%' ORDER BY run_id,ordinal) t",
        "SELECT row_to_json(t)::text FROM (SELECT * FROM lore_core.payloads "
        "WHERE logical_file_key LIKE 'drive.files.phase26-%%' ORDER BY run_id,payload_id) t",
        "SELECT row_to_json(t)::text FROM (SELECT o.* FROM lore_core.payload_occurrences o "
        "JOIN lore_core.processing_runs r USING (run_id) "
        "WHERE r.logical_file_key LIKE 'drive.files.phase26-%%' "
        "ORDER BY o.run_id,o.payload_id,o.occurrence_ordinal) t",
        "SELECT row_to_json(t)::text FROM (SELECT d.* FROM lore_core.diagnostics d "
        "JOIN lore_core.processing_runs r USING (run_id) "
        "WHERE r.logical_file_key LIKE 'drive.files.phase26-%%' AND d.origin='splitter' "
        "ORDER BY d.run_id,d.diagnostic_id) t",
    )
    values = []
    with connection.cursor() as cursor:
        for query in queries:
            cursor.execute(query)
            values.append(tuple(row[0] for row in cursor.fetchall()))
    connection.rollback()
    return tuple(values)


def test_real_dag_and_mapped_operator_preserve_each_exact_run_on_retry(monkeypatch):
    """Reverse-order same-file maps cannot drift to mutable latest-run state."""

    monkeypatch.setenv("LORE_CONFIG_PATH", str(CONFIG_PATH))
    dag_bag = DagBag(dag_folder=str(DAG_PATH), include_examples=False, safe_mode=False)
    assert dag_bag.import_errors == {}
    dag = dag_bag.dags["lore_splitter"]
    splitter = dag.task_dict["split_file"]
    audit = dag.task_dict["audit_file"]
    splitter_source = splitter.expand_input.value["file_item"]
    audit_source = audit.expand_input.value["file_item"]
    assert splitter_source.operator.task_id == audit_source.operator.task_id == "validated_file_items"
    assert splitter.downstream_task_ids == {"audit_file"}
    assert "split_file" in audit.upstream_task_ids
    assert str(audit.trigger_rule) == "all_done"

    with ephemeral_postgres() as connection:
        _seed_overlapping_runs(connection)
        operator = _operator(connection)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT latest_run_id::text FROM lore_core.processed_files "
                "WHERE logical_file_key=%s",
                (FILE_KEY,),
            )
            assert cursor.fetchone()[0] == RUN_A
        connection.rollback()

        map_one = ClaimTaskInstance(1, RUN_B)
        result_b = operator.execute({"ti": map_one})
        first_b_keys = _audit_keys(connection, RUN_B)

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT latest_run_id::text FROM lore_core.processed_files "
                "WHERE logical_file_key=%s",
                (FILE_KEY,),
            )
            assert cursor.fetchone()[0] == RUN_A
        connection.rollback()

        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE lore_core.processed_files SET latest_run_id=%s "
                "WHERE logical_file_key=%s AND latest_run_id=%s "
                "RETURNING latest_run_id::text",
                (RUN_B, FILE_KEY, RUN_A),
            )
            assert cursor.fetchone()[0] == RUN_B
            assert cursor.rowcount == 1
        connection.commit()

        map_zero = ClaimTaskInstance(0, RUN_A)
        result_a = operator.execute({"ti": map_zero})
        first_a_keys = _audit_keys(connection, RUN_A)
        retry_a = operator.execute({"ti": map_zero})
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT latest_run_id::text FROM lore_core.processed_files "
                "WHERE logical_file_key=%s",
                (FILE_KEY,),
            )
            assert cursor.fetchone()[0] == RUN_B
        connection.rollback()

        assert map_one.pulls == [
            {"task_ids": "split_file", "key": "lore_run_claim", "map_indexes": 1}
        ]
        assert map_zero.pulls == [
            {"task_ids": "split_file", "key": "lore_run_claim", "map_indexes": 0},
            {"task_ids": "split_file", "key": "lore_run_claim", "map_indexes": 0},
        ]
        assert result_b["run_id"] == RUN_B
        assert result_a["run_id"] == retry_a["run_id"] == RUN_A
        assert result_a["outcome_counts"] != result_b["outcome_counts"]
        assert any(":chunk:chunk-run-a:chunk_texts" in key for key in first_a_keys)
        assert not any(":chunk:chunk-run-a:" in key for key in first_b_keys)
        assert not any(":chunk:chunk-run-b:chunk_texts" in key for key in first_b_keys)
        assert _audit_keys(connection, RUN_B) == first_b_keys
        assert _audit_keys(connection, RUN_A) == first_a_keys
        assert len(first_a_keys) == len(set(first_a_keys))


def test_representative_formats_and_failed_skipped_runs_remain_honest():
    """Prove the risk-weighted format/status portfolio through durable facts."""

    with ephemeral_postgres() as connection:
        _seed_representative_runs(connection)
        repository = PostgresAuditSnapshotRepository(connection)
        operator = _operator(connection)
        observed = {}

        for map_index, (scenario, run_id, pipeline_type, status) in enumerate(
            REPRESENTATIVE_RUNS
        ):
            bundle = repository.load_exact_run(run_id, "audit/v1", AuditReadBounds())
            assert bundle.snapshot.run.status.value == status, scenario
            if status == "success":
                assert bundle.snapshot.chunks[0].pipeline_type == pipeline_type, scenario
            else:
                assert bundle.snapshot.chunks == (), scenario
                assert len(bundle.snapshot.processing_diagnostics) == 1, scenario
            assert _audit_keys(connection, run_id) == (), scenario

            result = operator.execute(
                {"ti": ClaimTaskInstance(map_index=map_index, run_id=run_id)}
            )
            observed[scenario] = (result["run_id"], result["status"])

        assert observed == {
            scenario: (run_id, "completed")
            for scenario, run_id, _pipeline_type, _status in REPRESENTATIVE_RUNS
        }
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT r.run_id::text,r.status,"
                "count(d.diagnostic_id) FILTER (WHERE d.code='AUDIT_COMPLETED') "
                "FROM lore_core.processing_runs r LEFT JOIN lore_core.diagnostics d "
                "ON d.run_id=r.run_id AND d.origin='audit_rule' "
                "WHERE r.logical_file_key LIKE 'drive.files.phase26-%%' "
                "GROUP BY r.run_id,r.status ORDER BY r.run_id"
            )
            durable_states = cursor.fetchall()
        connection.rollback()
        assert [(row[0], row[1]) for row in durable_states] == [
            (run_id, status)
            for _scenario, run_id, _pipeline_type, status in REPRESENTATIVE_RUNS
        ]
        assert all(row[2] == 1 for row in durable_states)


def test_audit_failure_is_isolated_from_sibling_and_processing_evidence():
    """Prove one audit failure cannot mutate processing truth or poison a sibling map."""

    failed_run = REPRESENTATIVE_RUNS[0][1]
    sibling_run = REPRESENTATIVE_RUNS[1][1]
    with ephemeral_postgres() as connection:
        _seed_representative_runs(connection)
        before = _processing_snapshot_bytes(connection)
        assert all(before)
        with connection.cursor() as cursor:
            cursor.execute(
                "CREATE FUNCTION phase26_fail_audit_completed() RETURNS trigger "
                "LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'bounded audit write failure'; "
                "END $$"
            )
            cursor.execute(
                "CREATE TRIGGER phase26_fail_one_audit BEFORE INSERT OR UPDATE "
                "ON lore_core.diagnostics FOR EACH ROW "
                f"WHEN (NEW.run_id='{failed_run}'::uuid AND NEW.code='AUDIT_COMPLETED') "
                "EXECUTE FUNCTION phase26_fail_audit_completed()"
            )
        connection.commit()

        operator = _operator(connection)
        failed_ti = ClaimTaskInstance(map_index=0, run_id=failed_run)
        with pytest.raises(AirflowFailException, match="completed_write_failed"):
            operator.execute({"ti": failed_ti})

        sibling_ti = ClaimTaskInstance(map_index=1, run_id=sibling_run)
        sibling = operator.execute({"ti": sibling_ti})
        after = _processing_snapshot_bytes(connection)

        assert failed_ti.pulls == [
            {"task_ids": "split_file", "key": "lore_run_claim", "map_indexes": 0}
        ]
        assert sibling_ti.pulls == [
            {"task_ids": "split_file", "key": "lore_run_claim", "map_indexes": 1}
        ]
        assert sibling["run_id"] == sibling_run
        assert sibling["status"] == "completed"
        assert after == before

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT run_id::text,code FROM lore_core.diagnostics "
                "WHERE run_id IN (%s,%s) AND origin='audit_rule' "
                "AND code IN ('AUDIT_COMPLETED','AUDIT_FAILED') ORDER BY run_id,code",
                (failed_run, sibling_run),
            )
            lifecycle_rows = cursor.fetchall()
        connection.rollback()
        assert lifecycle_rows == [
            (failed_run, "AUDIT_FAILED"),
            (sibling_run, "AUDIT_COMPLETED"),
        ]
