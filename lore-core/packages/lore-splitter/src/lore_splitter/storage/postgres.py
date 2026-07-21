from __future__ import annotations

import importlib
from typing import Any

from lore_core_domain.storage_contracts import (
    TableToastStoragePlan,
    TableToastStorageResult,
)
from lore_splitter.storage.schema import validate_table_storage_plan


class PostgresStorageError(RuntimeError):
    """Raised for unrecoverable Postgres adapter setup errors."""


class PostgresTableToastStore:
    """Postgres-backed table TOAST store using a caller-provided connection."""

    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def store_table(self, plan: TableToastStoragePlan) -> TableToastStorageResult:
        validate_table_storage_plan(plan)
        sql = _psycopg_sql()
        cursor = self.connection.cursor()
        try:
            with cursor:
                _create_schema(cursor, sql, plan)
                _drop_staging(cursor, sql, plan)
                _create_staging_table(cursor, sql, plan)
                _copy_rows(cursor, sql, plan)
                _acquire_advisory_lock(cursor, sql, plan)
                existed = _final_table_exists(cursor, sql, plan)
                if existed:
                    _drop_final(cursor, sql, plan)
                _rename_staging_to_final(cursor, sql, plan)
            _commit(self.connection)
        except Exception as exc:  # noqa: BLE001 - diagnostics must preserve adapter failures.
            _cleanup_failed_staging(self.connection, sql, plan, exc)
            return TableToastStorageResult(
                toast_id=plan.toast_id,
                schema_name=plan.schema_name,
                table_name=plan.table_name,
                row_count=0,
                action="failed",
                warnings=plan.warnings,
                diagnostics=(*plan.diagnostics, f"postgres_storage_failed:{exc}"),
                source=plan.source,
                source_kind=plan.source_kind,
                source_checksum=plan.source_checksum,
                source_location=plan.source_location,
                workbook_checksum=plan.workbook_checksum,
                sheet=plan.sheet,
                range=plan.range,
            )

        return TableToastStorageResult.from_plan(plan, action="replaced" if existed else "created")


def _psycopg_sql() -> Any:
    try:
        psycopg = importlib.import_module("psycopg")
    except ModuleNotFoundError as exc:
        raise PostgresStorageError(
            "psycopg is required for PostgresTableToastStore; install splitter[postgres]"
        ) from exc
    return psycopg.sql


def _create_schema(cursor: Any, sql: Any, plan: TableToastStoragePlan) -> None:
    cursor.execute(
        sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(plan.schema_name))
    )


def _drop_staging(cursor: Any, sql: Any, plan: TableToastStoragePlan) -> None:
    cursor.execute(
        sql.SQL("DROP TABLE IF EXISTS {}.{} /* staging */").format(
            sql.Identifier(plan.schema_name),
            sql.Identifier(plan.staging_table_name),
        )
    )


def _create_staging_table(cursor: Any, sql: Any, plan: TableToastStoragePlan) -> None:
    column_definitions = [
        sql.SQL("{} {} NOT NULL").format(
            sql.Identifier("_splitter_row_number"),
            sql.SQL("integer"),
        ),
        sql.SQL("{} {} NOT NULL").format(
            sql.Identifier("_splitter_source_row"),
            sql.SQL("integer"),
        ),
        sql.SQL("{} {} NOT NULL").format(sql.Identifier("_splitter_source_range"), sql.SQL("text")),
    ]
    for column in plan.columns:
        nullability = sql.SQL("") if column.nullable else sql.SQL(" NOT NULL")
        column_definitions.append(
            sql.SQL("{} {}{}").format(
                sql.Identifier(column.sql_name),
                sql.SQL(_storage_sql_type(column.storage_type)),
                nullability,
            )
        )

    cursor.execute(
        sql.SQL("CREATE TABLE {}.{} ({})").format(
            sql.Identifier(plan.schema_name),
            sql.Identifier(plan.staging_table_name),
            sql.SQL(", ").join(column_definitions),
        )
    )


def _copy_rows(cursor: Any, sql: Any, plan: TableToastStoragePlan) -> None:
    copy_columns = (
        "_splitter_row_number",
        "_splitter_source_row",
        "_splitter_source_range",
        *(column.sql_name for column in plan.columns),
    )
    statement = sql.SQL("COPY {}.{} ({}) FROM STDIN").format(
        sql.Identifier(plan.schema_name),
        sql.Identifier(plan.staging_table_name),
        sql.SQL(", ").join(sql.Identifier(column) for column in copy_columns),
    )
    with cursor.copy(statement) as copy:
        for row in plan.rows:
            copy.write_row(
                (
                    row.row_number,
                    row.source_row,
                    row.source_range,
                    *(row.values.get(column.sql_name) for column in plan.columns),
                )
            )


def _acquire_advisory_lock(cursor: Any, sql: Any, plan: TableToastStoragePlan) -> None:
    cursor.execute(
        sql.SQL("SELECT pg_advisory_xact_lock(%s)"),
        (plan.advisory_lock_key,),
    )


def _final_table_exists(cursor: Any, sql: Any, plan: TableToastStoragePlan) -> bool:
    cursor.execute(
        sql.SQL("SELECT to_regclass(%s) IS NOT NULL"),
        (f"{plan.schema_name}.{plan.table_name}",),
    )
    row = cursor.fetchone()
    return bool(row and row[0])


def _drop_final(cursor: Any, sql: Any, plan: TableToastStoragePlan) -> None:
    cursor.execute(
        sql.SQL("DROP TABLE IF EXISTS {}.{}").format(
            sql.Identifier(plan.schema_name),
            sql.Identifier(plan.table_name),
        )
    )


def _rename_staging_to_final(cursor: Any, sql: Any, plan: TableToastStoragePlan) -> None:
    cursor.execute(
        sql.SQL("ALTER TABLE {}.{} RENAME TO {}").format(
            sql.Identifier(plan.schema_name),
            sql.Identifier(plan.staging_table_name),
            sql.Identifier(plan.table_name),
        )
    )


def _cleanup_failed_staging(
    connection: Any,
    sql: Any,
    plan: TableToastStoragePlan,
    original_error: Exception,
) -> None:
    _rollback(connection)
    marker = getattr(connection, "mark_failed", None)
    if marker is not None:
        marker()
    try:
        cursor = connection.cursor()
        with cursor:
            _drop_staging(cursor, sql, plan)
        _commit(connection)
    except Exception as cleanup_error:  # noqa: BLE001 - append cleanup context to original error.
        raise PostgresStorageError(
            f"failed to clean staging table after {original_error}: {cleanup_error}"
        ) from cleanup_error


def _commit(connection: Any) -> None:
    commit = getattr(connection, "commit", None)
    if commit is not None:
        commit()


def _rollback(connection: Any) -> None:
    rollback = getattr(connection, "rollback", None)
    if rollback is not None:
        rollback()


def _storage_sql_type(storage_type: str) -> str:
    return {
        "boolean": "boolean",
        "date": "date",
        "numeric": "numeric",
        "text": "text",
    }.get(storage_type, "text")
