"""Airflow 3 hook-backed edges for exact-run deterministic auditing."""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import Any

from lore_audit.engine_contracts import PayloadResolutionFact, PhysicalResolution
from lore_audit.persistence import PostgresAuditResultWriter
from lore_audit.snapshot_repository import AuditReadBounds, PostgresAuditSnapshotRepository

_ERROR_MESSAGES = {
    "invalid_config": "audit adapter configuration is invalid",
    "postgres_unavailable": "audit database capability is unavailable",
    "table_check_failed": "audit table capability check failed",
    "s3_check_failed": "audit object capability check failed",
}


class AuditAirflowAdapterError(RuntimeError):
    """Fixed-category adapter failure safe for the service boundary."""

    def __init__(self, category: str) -> None:
        if category not in _ERROR_MESSAGES:
            category = "s3_check_failed"
        self.category = category
        super().__init__(_ERROR_MESSAGES[category])


@dataclass(frozen=True)
class _S3CapabilityResolver:
    s3_conn_id: str = field(repr=False)
    injected_hook: Any | None = field(default=None, repr=False)
    postgres_connection: Any = field(default=None, repr=False)
    _hook: Any | None = field(default=None, init=False, repr=False, compare=False)
    _provider_missing: bool = field(default=False, init=False, repr=False, compare=False)

    def resolve(
        self, facts: tuple[PayloadResolutionFact, ...]
    ) -> tuple[PayloadResolutionFact, ...]:
        values = tuple(facts)
        if any(not isinstance(item, PayloadResolutionFact) for item in values):
            raise AuditAirflowAdapterError("s3_check_failed")
        hook = self._get_hook() if any(self._requires_s3_check(item) for item in values) else None
        resolved: list[PayloadResolutionFact] = []
        for item in values:
            if self._requires_table_check(item):
                resolved.append(self._resolve_table(item))
                continue
            if not self._requires_s3_check(item):
                resolved.append(item)
                continue
            physical = item.physical
            if physical is None:
                raise AuditAirflowAdapterError("s3_check_failed")
            identity = dict(physical.identity)
            if set(identity) != {"bucket", "object_key"} or not all(
                isinstance(identity[key], str) and identity[key]
                for key in ("bucket", "object_key")
            ):
                raise AuditAirflowAdapterError("s3_check_failed")

            if hook is None:
                exists = False
            else:
                try:
                    metadata = hook.head_object(
                        key=identity["object_key"],
                        bucket_name=identity["bucket"],
                    )
                except Exception as exc:  # noqa: BLE001 - map to a fixed safe category.
                    raise AuditAirflowAdapterError("s3_check_failed") from exc
                # Presence alone is the bounded fact. Never project hook metadata or content.
                exists = metadata is not None
            resolved.append(self._with_resolution(item, exists))
        return tuple(resolved)

    def _resolve_table(self, item: PayloadResolutionFact) -> PayloadResolutionFact:
        physical = item.physical
        if physical is None:
            raise AuditAirflowAdapterError("table_check_failed")
        identity = dict(physical.identity)
        if set(identity) != {"schema_name", "table_name"} or not all(
            isinstance(identity[key], str) and identity[key]
            for key in ("schema_name", "table_name")
        ):
            raise AuditAirflowAdapterError("table_check_failed")

        cursor = None
        try:
            cursor = self.postgres_connection.cursor()
            cursor.execute(
                "SELECT EXISTS ("
                "SELECT 1 FROM pg_catalog.pg_class AS c "
                "JOIN pg_catalog.pg_namespace AS n ON n.oid=c.relnamespace "
                "WHERE n.nspname=%s AND c.relname=%s AND c.relkind IN ('r','p')"
                ")",
                (identity["schema_name"], identity["table_name"]),
            )
            row = cursor.fetchone()
            if not isinstance(row, (tuple, list)) or len(row) != 1 or not isinstance(row[0], bool):
                raise ValueError("catalog result is invalid")
            exists = row[0]
        except Exception as exc:  # noqa: BLE001 - map to a fixed safe category.
            try:
                self.postgres_connection.rollback()
            except Exception:  # noqa: BLE001 - preserve the fixed primary category.
                pass
            raise AuditAirflowAdapterError("table_check_failed") from exc
        else:
            try:
                # End the shared connection's read transaction before later audit writes.
                self.postgres_connection.rollback()
            except Exception as exc:  # noqa: BLE001 - map to a fixed safe category.
                raise AuditAirflowAdapterError("table_check_failed") from exc
        finally:
            if cursor is not None:
                cursor.close()
        return self._with_resolution(item, exists)

    @staticmethod
    def _with_resolution(item: PayloadResolutionFact, exists: bool) -> PayloadResolutionFact:
        projection = item.to_dict()
        physical_projection = projection.pop("physical")
        physical_projection["resolved"] = exists
        return PayloadResolutionFact(
            **projection,
            physical=PhysicalResolution(**physical_projection),
        )

    @staticmethod
    def _requires_s3_check(item: PayloadResolutionFact) -> bool:
        return item.kind == "image" and item.registered

    @staticmethod
    def _requires_table_check(item: PayloadResolutionFact) -> bool:
        return item.kind == "table" and item.registered

    def _get_hook(self) -> Any | None:
        if self.injected_hook is not None:
            return self.injected_hook
        if self._provider_missing:
            return None
        if self._hook is not None:
            return self._hook
        try:
            module = importlib.import_module("airflow.providers.amazon.aws.hooks.s3")
            hook = module.S3Hook(aws_conn_id=self.s3_conn_id)
        except (ImportError, ModuleNotFoundError):
            object.__setattr__(self, "_provider_missing", True)
            return None
        except Exception as exc:  # noqa: BLE001 - map to a fixed safe category.
            raise AuditAirflowAdapterError("s3_check_failed") from exc
        object.__setattr__(self, "_hook", hook)
        return hook


@dataclass(frozen=True)
class AirflowAuditAdapters:
    """Frozen capabilities created only after an operator validates its claim."""

    reader: PostgresAuditSnapshotRepository
    writer: PostgresAuditResultWriter
    payload_resolver: _S3CapabilityResolver
    bounds: AuditReadBounds


def build_airflow_audit_adapters(
    postgres_conn_id: str,
    s3_conn_id: str,
    bounds: AuditReadBounds | None = None,
    *,
    postgres_hook: Any | None = None,
    s3_hook: Any | None = None,
) -> AirflowAuditAdapters:
    """Build a dedicated reader/writer and lazy object resolver from connection IDs."""

    if (
        not isinstance(postgres_conn_id, str)
        or not postgres_conn_id
        or not isinstance(s3_conn_id, str)
        or not s3_conn_id
        or (bounds is not None and not isinstance(bounds, AuditReadBounds))
    ):
        raise AuditAirflowAdapterError("invalid_config")
    selected_bounds = bounds if bounds is not None else AuditReadBounds()

    try:
        hook = postgres_hook
        if hook is None:
            module = importlib.import_module("airflow.providers.postgres.hooks.postgres")
            hook = module.PostgresHook(postgres_conn_id=postgres_conn_id)
        connection = hook.get_conn()
    except Exception as exc:  # noqa: BLE001 - map to a fixed safe category.
        raise AuditAirflowAdapterError("postgres_unavailable") from exc

    return AirflowAuditAdapters(
        reader=PostgresAuditSnapshotRepository(connection),
        writer=PostgresAuditResultWriter(connection),
        payload_resolver=_S3CapabilityResolver(s3_conn_id, s3_hook, connection),
        bounds=selected_bounds,
    )


__all__ = [
    "AirflowAuditAdapters",
    "AuditAirflowAdapterError",
    "build_airflow_audit_adapters",
]
