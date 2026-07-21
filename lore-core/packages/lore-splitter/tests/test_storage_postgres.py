from __future__ import annotations

import importlib
import sys
import types
from dataclasses import replace
from typing import Any

import pytest
from lore_splitter.markdown import ToastThresholds, classify_table, profile_table
from lore_splitter.storage import build_table_storage_plan
from lore_splitter.storage import (
    StoragePlanError,
    TableToastStoragePlan,
)
from tests.test_markdown_render import _table_data


def test_psycopg_is_a_main_dependency() -> None:
    """lore-splitter ships psycopg as a main dep (not optional); verify it is importable."""
    import psycopg  # noqa: F401 — presence check

    assert psycopg is not None


def test_fake_psycopg_harness_records_composable_identifier_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    psycopg = install_fake_psycopg(monkeypatch)

    statement = psycopg.sql.SQL("SELECT {} FROM {}.{}").format(
        psycopg.sql.Identifier("amount"),
        psycopg.sql.Identifier("splitter_toast"),
        psycopg.sql.Identifier("toast_tbl_0123456789abcdefabcd"),
    )

    assert statement.template == "SELECT {} FROM {}.{}"
    assert [identifier.name for identifier in statement.identifiers] == [
        "amount",
        "splitter_toast",
        "toast_tbl_0123456789abcdefabcd",
    ]
    assert all(
        isinstance(identifier, psycopg.sql.Identifier) for identifier in statement.identifiers
    )


def test_postgres_module_import_is_deferred_until_runtime_dependency_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delitem(sys.modules, "psycopg", raising=False)

    module = importlib.import_module("lore_splitter.storage.postgres")

    assert module.PostgresTableToastStore is not None
    assert "psycopg" not in sys.modules


def test_postgres_adapter_uses_composable_identifiers_for_schema_tables_and_columns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    psycopg = install_fake_psycopg(monkeypatch)
    connection = FakeConnection(final_tables=set())
    store = _postgres_store(connection)
    plan = _storage_plan()

    store.store_table(plan)

    composable_statements = [
        statement for statement, _params in connection.cursor_obj.executed if statement is not None
    ]
    identifiers = [
        identifier.name
        for statement in composable_statements
        for identifier in statement.identifiers
    ]
    assert plan.schema_name in identifiers
    assert plan.staging_table_name in identifiers
    assert plan.table_name in identifiers
    assert {column.sql_name for column in plan.columns}.issubset(identifiers)
    assert all(
        isinstance(identifier, psycopg.sql.Identifier)
        for statement in composable_statements
        for identifier in statement.identifiers
    )
    assert not any(
        plan.staging_table_name in statement.template or plan.table_name in statement.template
        for statement in composable_statements
    )


def test_postgres_store_loads_staging_with_copy_then_promotes_after_advisory_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_psycopg(monkeypatch)
    connection = FakeConnection(final_tables=set())
    store = _postgres_store(connection)
    plan = _storage_plan()

    result = store.store_table(plan)

    events = connection.cursor_obj.events
    assert result.action == "created"
    assert result.schema_name == plan.schema_name
    assert result.table_name == plan.table_name
    assert result.row_count == plan.row_count
    assert result.source == plan.source
    assert result.source_kind == plan.source_kind
    assert result.source_checksum == plan.source_checksum
    assert result.source_location == plan.source_location
    assert result.workbook_checksum == plan.workbook_checksum
    assert result.sheet == plan.sheet
    assert result.range == plan.range
    assert result.diagnostics == plan.diagnostics

    assert events.index("create_schema") < events.index("drop_staging")
    assert events.index("drop_staging") < events.index("create_staging")
    assert events.index("create_staging") < events.index("copy")
    assert events.index("copy") < events.index("advisory_lock")
    assert events.index("advisory_lock") < events.index("rename_staging")
    assert "drop_final" not in events
    assert connection.cursor_obj.lock_keys == [plan.advisory_lock_key]
    assert len(connection.cursor_obj.copies) == 1
    copy = connection.cursor_obj.copies[0]
    assert copy.statement.identifiers[0].name == plan.schema_name
    assert copy.statement.identifiers[1].name == plan.staging_table_name
    assert copy.rows == [
        (
            storage_row.row_number,
            storage_row.source_row,
            storage_row.source_range,
            *(storage_row.values[column.sql_name] for column in plan.columns),
        )
        for storage_row in plan.rows
    ]
    assert connection.commits == 1
    assert connection.rollbacks == 0


def test_postgres_store_preserves_prior_final_table_when_copy_load_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_psycopg(monkeypatch)
    plan = _storage_plan()
    connection = FakeConnection(final_tables={plan.table_name}, fail_copy_after_rows=1)
    store = _postgres_store(connection)

    result = store.store_table(plan)

    assert result.action == "failed"
    assert result.row_count == 0
    assert any("copy failed after 1 rows" in diagnostic for diagnostic in result.diagnostics)
    assert "drop_final" not in connection.cursor_obj.events
    assert "rename_staging" not in connection.cursor_obj.events
    assert connection.cursor_obj.events[-1] == "cleanup_staging"
    assert plan.table_name in connection.final_tables
    assert connection.commits == 1


def test_postgres_store_rejects_tampered_plan_identifiers_before_ddl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_psycopg(monkeypatch)
    plan = _storage_plan()
    tampered = replace(plan, staging_table_name="customer_orders")
    connection = FakeConnection(final_tables={plan.table_name, "customer_orders"})
    store = _postgres_store(connection)

    with pytest.raises(StoragePlanError, match="invalid staging table name"):
        store.store_table(tampered)

    assert connection.cursor_obj.events == []
    assert connection.commits == 0
    assert connection.rollbacks == 0
    assert "customer_orders" in connection.final_tables


def test_postgres_store_replaces_existing_final_table_after_successful_staging_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_psycopg(monkeypatch)
    plan = _storage_plan()
    connection = FakeConnection(final_tables={plan.table_name}, existing_shapes={"legacy_shape"})
    store = _postgres_store(connection)

    result = store.store_table(plan)

    assert result.action == "replaced"
    assert connection.cursor_obj.events.index("copy") < connection.cursor_obj.events.index(
        "drop_final"
    )
    assert connection.cursor_obj.events.index("drop_final") < connection.cursor_obj.events.index(
        "rename_staging"
    )
    assert plan.table_name in connection.final_tables


def test_postgres_result_manifest_fields_include_actions_warnings_diagnostics_and_lineage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_psycopg(monkeypatch)
    plan = _storage_plan()
    plan = replace(plan, warnings=("storage_type_downgraded-to-text:example",))
    connection = FakeConnection(final_tables=set())
    store = _postgres_store(connection)

    result = store.store_table(plan)
    manifest_entry = result.to_manifest_entry()

    assert manifest_entry["action"] == "created"
    assert manifest_entry["schema"] == plan.schema_name
    assert manifest_entry["table_name"] == plan.table_name
    assert manifest_entry["row_count"] == plan.row_count
    assert manifest_entry["warnings"] == ["storage_type_downgraded-to-text:example"]
    assert manifest_entry["diagnostics"] == list(plan.diagnostics)
    assert manifest_entry["source"] == plan.source
    assert manifest_entry["source_kind"] == plan.source_kind
    assert manifest_entry["source_checksum"] == plan.source_checksum
    assert manifest_entry["source_location"] == plan.source_location
    assert manifest_entry["workbook_checksum"] == plan.workbook_checksum
    assert manifest_entry["sheet"] == plan.sheet
    assert manifest_entry["range"] == plan.range


def _postgres_store(connection: FakeConnection) -> Any:
    from lore_splitter.storage.postgres import PostgresTableToastStore

    return PostgresTableToastStore(connection)


def _storage_plan() -> TableToastStoragePlan:
    table = _table_data(
        "Summary",
        1,
        "A1:C4",
        rows=(
            ("Region", "Amount", "Invoice Date"),
            ("North", 125.5, "2026-02-01"),
            ("South", 50, "2026-02-02"),
            ("West", 75, "2026-02-03"),
        ),
    )
    profile = profile_table(table)
    decision = classify_table(
        table,
        profile,
        thresholds=ToastThresholds(max_inline_markdown_bytes=1),
    )
    return build_table_storage_plan(table, profile, decision)


def install_fake_psycopg(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    fake = types.ModuleType("psycopg")
    fake.sql = FakeSqlModule
    monkeypatch.setitem(sys.modules, "psycopg", fake)
    return fake


class FakeIdentifier:
    def __init__(self, name: str) -> None:
        self.name = name
        self.identifiers = (self,)


class FakeComposable:
    def __init__(
        self,
        template: str,
        *,
        parts: tuple[Any, ...] = (),
        identifiers: tuple[FakeIdentifier, ...] = (),
    ) -> None:
        self.template = template
        self.parts = parts
        self.identifiers = identifiers

    def format(self, *parts: Any, **named_parts: Any) -> FakeComposable:
        all_parts = (*parts, *named_parts.values())
        return FakeComposable(
            self.template,
            parts=all_parts,
            identifiers=tuple(
                identifier
                for part in all_parts
                for identifier in getattr(part, "identifiers", ())
            ),
        )

    def join(self, parts: Any) -> FakeComposable:
        joined_parts = tuple(parts)
        return FakeComposable(
            self.template,
            parts=joined_parts,
            identifiers=tuple(
                identifier
                for part in joined_parts
                for identifier in getattr(part, "identifiers", ())
            ),
        )


class FakeSqlModule:
    SQL = FakeComposable
    Identifier = FakeIdentifier


class FakeCopy:
    def __init__(self, statement: FakeComposable, *, fail_after_rows: int | None = None) -> None:
        self.statement = statement
        self.fail_after_rows = fail_after_rows
        self.rows: list[tuple[Any, ...]] = []

    def __enter__(self) -> FakeCopy:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        return False

    def write_row(self, row: tuple[Any, ...]) -> None:
        if self.fail_after_rows is not None and len(self.rows) >= self.fail_after_rows:
            raise RuntimeError(f"copy failed after {self.fail_after_rows} rows")
        self.rows.append(tuple(row))


class FakeCursor:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection
        self.executed: list[tuple[FakeComposable | None, tuple[Any, ...] | None]] = []
        self.events: list[str] = []
        self.copies: list[FakeCopy] = []
        self.lock_keys: list[int] = []
        self._last_exists: bool | None = None

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        return False

    def execute(self, statement: FakeComposable, params: tuple[Any, ...] | None = None) -> None:
        self.executed.append((statement, params))
        template = statement.template
        if "CREATE SCHEMA" in template:
            self.events.append("create_schema")
        elif "DROP TABLE" in template and "staging" in template.lower():
            if self.connection.promoted:
                self.events.append("drop_staging_after_rename")
            elif self.connection.failed:
                self.events.append("cleanup_staging")
            else:
                self.events.append("drop_staging")
        elif "CREATE TABLE" in template:
            self.events.append("create_staging")
        elif "pg_advisory_xact_lock" in template:
            self.events.append("advisory_lock")
            self.lock_keys.append(params[0] if params else None)
        elif "to_regclass" in template:
            self.events.append("check_final")
            table_name = params[0].split(".")[-1] if params else ""
            self._last_exists = table_name in self.connection.final_tables
        elif "DROP TABLE" in template:
            self.events.append("drop_final")
        elif "ALTER TABLE" in template and "RENAME TO" in template:
            self.events.append("rename_staging")
            self.connection.promoted = True
            final_name = statement.identifiers[-1].name
            self.connection.final_tables.add(final_name)

    def copy(self, statement: FakeComposable) -> FakeCopy:
        self.events.append("copy")
        copy = FakeCopy(statement, fail_after_rows=self.connection.fail_copy_after_rows)
        self.copies.append(copy)
        return copy

    def fetchone(self) -> tuple[bool]:
        return (bool(self._last_exists),)


class FakeConnection:
    def __init__(
        self,
        *,
        final_tables: set[str],
        fail_copy_after_rows: int | None = None,
        existing_shapes: set[str] | None = None,
    ) -> None:
        self.final_tables = final_tables
        self.fail_copy_after_rows = fail_copy_after_rows
        self.existing_shapes = existing_shapes or set()
        self.cursor_obj = FakeCursor(self)
        self.commits = 0
        self.rollbacks = 0
        self.promoted = False
        self.failed = False

    def cursor(self) -> FakeCursor:
        return self.cursor_obj

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def mark_failed(self) -> None:
        self.failed = True
