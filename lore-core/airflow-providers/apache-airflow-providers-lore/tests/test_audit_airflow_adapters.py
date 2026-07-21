from __future__ import annotations

import importlib
from dataclasses import FrozenInstanceError

import pytest

from lore_audit.engine_contracts import (
    PayloadResolutionFact,
    PhysicalResolution,
)
from lore_audit.snapshot_repository import (
    AuditReadBounds,
    PostgresAuditSnapshotRepository,
)
from lore_audit.persistence import PostgresAuditResultWriter


class PostgresHook:
    def __init__(self, connection):
        self.connection = connection
        self.get_conn_calls = 0

    def get_conn(self):
        self.get_conn_calls += 1
        return self.connection


class TableConnection:
    def __init__(self, *, exists=True, error=None):
        self.exists = exists
        self.error = error
        self.calls = []
        self.rollbacks = 0

    def cursor(self):
        connection = self

        class Cursor:
            def execute(self, sql, params):
                connection.calls.append((" ".join(sql.split()), params))
                if connection.error:
                    raise connection.error

            def fetchone(self):
                return (connection.exists,)

            def close(self):
                pass

        return Cursor()

    def rollback(self):
        self.rollbacks += 1


class S3Hook:
    def __init__(self, *, result=object(), error=None):
        self.result = result
        self.error = error
        self.calls = []

    def head_object(self, *, key, bucket_name):
        self.calls.append({"key": key, "bucket_name": bucket_name})
        if self.error:
            raise self.error
        return self.result


def image_fact(*, registered=True, resolved=True):
    identity = {"bucket": "lore-files", "object_key": "images/a.png"}
    return PayloadResolutionFact(
        payload_id="image-1",
        kind="image",
        registered=registered,
        occurrence_count=1,
        registration_identity=(
            {
                **identity,
                "content_type": "image/png",
                "extension": ".png",
                "byte_size": 4,
                "checksum_sha256": "a" * 64,
                "source_kind": "document",
                "source_checksum": "b" * 64,
                "source_location": {"page": 1},
                "width": 1,
                "height": 1,
                "dimensions": {"width": 1, "height": 1},
            }
            if registered
            else {}
        ),
        physical=(
            PhysicalResolution(
                storage_kind="s3",
                resolved=resolved,
                identity=identity,
                checksum_sha256="a" * 64,
                byte_size=4,
                content_type="image/png",
            )
            if registered
            else None
        ),
    )


def table_fact():
    return PayloadResolutionFact(
        payload_id="table-1",
        kind="table",
        registered=True,
        occurrence_count=1,
        registration_identity={
            "schema_name": "lore_toast",
            "table_name": "table_1",
            "row_count": 1,
            "column_count": 1,
            "columns": ["value"],
            "source_kind": "workbook",
            "source_checksum": "b" * 64,
            "source_location": {"sheet": "Sheet1", "range": "A1"},
            "profile_signature": "c" * 64,
        },
        physical=PhysicalResolution(
            storage_kind="postgres",
            resolved=True,
            identity={"schema_name": "lore_toast", "table_name": "table_1"},
        ),
    )


def test_factory_uses_one_injected_postgres_connection_and_is_frozen():
    from airflow.providers.lore.adapters.airflow_audit_adapters import build_airflow_audit_adapters

    connection = object()
    postgres_hook = PostgresHook(connection)
    s3_hook = S3Hook()
    adapters = build_airflow_audit_adapters(
        postgres_conn_id="postgres_audit",
        s3_conn_id="s3_audit",
        bounds=AuditReadBounds(max_chunks=7),
        postgres_hook=postgres_hook,
        s3_hook=s3_hook,
    )

    assert postgres_hook.get_conn_calls == 1
    assert isinstance(adapters.reader, PostgresAuditSnapshotRepository)
    assert isinstance(adapters.writer, PostgresAuditResultWriter)
    assert adapters.reader.connection is connection
    assert adapters.writer.connection is connection
    assert adapters.bounds.max_chunks == 7
    with pytest.raises(FrozenInstanceError):
        adapters.reader = None
    assert "postgres_audit" not in repr(adapters)
    assert "s3_audit" not in repr(adapters)


def test_factory_forwards_exact_connection_ids_through_airflow_3_hooks(monkeypatch):
    from airflow.providers.lore.adapters.airflow_audit_adapters import build_airflow_audit_adapters

    connection = object()
    calls = []

    class DynamicPostgresHook(PostgresHook):
        def __init__(self, *, postgres_conn_id):
            calls.append(("postgres", postgres_conn_id))
            super().__init__(connection)

    class DynamicS3Hook(S3Hook):
        def __init__(self, *, aws_conn_id):
            calls.append(("s3", aws_conn_id))
            super().__init__()

    real_import = importlib.import_module

    def fake_import(name):
        if name == "airflow.providers.postgres.hooks.postgres":
            return type("PostgresModule", (), {"PostgresHook": DynamicPostgresHook})
        if name == "airflow.providers.amazon.aws.hooks.s3":
            return type("S3Module", (), {"S3Hook": DynamicS3Hook})
        return real_import(name)

    monkeypatch.setattr(importlib, "import_module", fake_import)
    adapters = build_airflow_audit_adapters("postgres.exact", "s3.exact")

    assert calls == [("postgres", "postgres.exact")]
    adapters.payload_resolver.resolve((image_fact(),))
    assert calls == [("postgres", "postgres.exact"), ("s3", "s3.exact")]


def test_s3_is_lazy_and_registered_physical_identities_only():
    from airflow.providers.lore.adapters.airflow_audit_adapters import build_airflow_audit_adapters

    hook = S3Hook()
    adapters = build_airflow_audit_adapters(
        "postgres",
        "s3",
        postgres_hook=PostgresHook(TableConnection()),
        s3_hook=hook,
    )

    assert adapters.payload_resolver.resolve((table_fact(), image_fact(registered=False))) == (
        table_fact(),
        image_fact(registered=False),
    )
    assert hook.calls == []

    resolved = adapters.payload_resolver.resolve((image_fact(),))
    assert resolved[0].physical.resolved is True
    assert hook.calls == [{"key": "images/a.png", "bucket_name": "lore-files"}]


@pytest.mark.parametrize("exists", [True, False])
def test_registered_table_resolution_uses_parameterized_catalog_presence(exists):
    from airflow.providers.lore.adapters.airflow_audit_adapters import build_airflow_audit_adapters

    connection = TableConnection(exists=exists)
    adapters = build_airflow_audit_adapters(
        "postgres",
        "s3",
        postgres_hook=PostgresHook(connection),
        s3_hook=S3Hook(),
    )

    result = adapters.payload_resolver.resolve((table_fact(),))

    assert result[0].physical.resolved is exists
    assert len(connection.calls) == 1
    sql, params = connection.calls[0]
    assert "pg_catalog.pg_class" in sql
    assert "pg_catalog.pg_namespace" in sql
    assert params == ("lore_toast", "table_1")
    assert "lore_toast" not in sql
    assert "table_1" not in sql


def test_registered_table_rejects_malformed_identity_before_catalog_query():
    from airflow.providers.lore.adapters.airflow_audit_adapters import (
        AuditAirflowAdapterError,
        build_airflow_audit_adapters,
    )

    connection = TableConnection()
    malformed = table_fact().to_dict()
    physical = malformed.pop("physical")
    physical["identity"] = {"schema_name": "lore_toast", "table_name": ""}
    fact = PayloadResolutionFact(**malformed, physical=PhysicalResolution(**physical))
    adapters = build_airflow_audit_adapters(
        "postgres", "s3", postgres_hook=PostgresHook(connection), s3_hook=S3Hook()
    )

    with pytest.raises(AuditAirflowAdapterError, match="capability check failed"):
        adapters.payload_resolver.resolve((fact,))

    assert connection.calls == []


def test_registered_table_catalog_errors_are_fixed_and_redacted():
    from airflow.providers.lore.adapters.airflow_audit_adapters import (
        AuditAirflowAdapterError,
        build_airflow_audit_adapters,
    )

    canaries = "postgresql://user:password@host/db SELECT private source text"
    connection = TableConnection(error=RuntimeError(canaries))
    adapters = build_airflow_audit_adapters(
        "postgres", "s3", postgres_hook=PostgresHook(connection), s3_hook=S3Hook()
    )

    with pytest.raises(AuditAirflowAdapterError) as error:
        adapters.payload_resolver.resolve((table_fact(),))

    assert str(error.value) == "audit table capability check failed"
    assert canaries not in str(error.value)


def test_missing_s3_optional_capability_becomes_unresolved(monkeypatch):
    from airflow.providers.lore.adapters.airflow_audit_adapters import build_airflow_audit_adapters

    real_import = importlib.import_module

    def missing_s3(name):
        if name == "airflow.providers.amazon.aws.hooks.s3":
            raise ModuleNotFoundError("signed-url-secret")
        return real_import(name)

    monkeypatch.setattr(importlib, "import_module", missing_s3)
    adapters = build_airflow_audit_adapters(
        "postgres", "s3", postgres_hook=PostgresHook(object())
    )

    result = adapters.payload_resolver.resolve((image_fact(),))
    assert result[0].physical.resolved is False
    assert result[0].physical.identity == image_fact().physical.identity


def test_s3_check_is_metadata_only_and_does_not_return_hook_content():
    from airflow.providers.lore.adapters.airflow_audit_adapters import build_airflow_audit_adapters

    canary = {
        "Body": b"payload-bytes-secret",
        "signed_url": "https://bucket.invalid/key?X-Amz-Signature=secret",
        "password": "secret-password",
    }
    hook = S3Hook(result=canary)
    adapters = build_airflow_audit_adapters(
        "postgres",
        "s3",
        postgres_hook=PostgresHook(object()),
        s3_hook=hook,
    )

    result = adapters.payload_resolver.resolve((image_fact(),))
    projection = repr(result[0].to_dict())

    assert result[0].physical.resolved is True
    for secret in ("payload-bytes-secret", "X-Amz-Signature", "secret-password"):
        assert secret not in projection


def test_unexpected_hook_errors_are_fixed_and_redacted():
    from airflow.providers.lore.adapters.airflow_audit_adapters import (
        AuditAirflowAdapterError,
        build_airflow_audit_adapters,
    )

    canaries = (
        "postgresql://user:password@host/db",
        "https://bucket.invalid/key?X-Amz-Signature=secret",
        "private source text",
    )
    hook = S3Hook(error=RuntimeError(" ".join(canaries)))
    adapters = build_airflow_audit_adapters(
        "postgres",
        "s3",
        postgres_hook=PostgresHook(object()),
        s3_hook=hook,
    )

    with pytest.raises(AuditAirflowAdapterError) as error:
        adapters.payload_resolver.resolve((image_fact(),))

    assert str(error.value) == "audit object capability check failed"
    for secret in canaries:
        assert secret not in str(error.value)


@pytest.mark.parametrize("postgres_conn_id,s3_conn_id", [("", "s3"), ("postgres", "")])
def test_connection_ids_are_non_empty_strings(postgres_conn_id, s3_conn_id):
    from airflow.providers.lore.adapters.airflow_audit_adapters import (
        AuditAirflowAdapterError,
        build_airflow_audit_adapters,
    )

    with pytest.raises(AuditAirflowAdapterError, match="audit adapter configuration is invalid"):
        build_airflow_audit_adapters(
            postgres_conn_id,
            s3_conn_id,
            postgres_hook=PostgresHook(object()),
        )
