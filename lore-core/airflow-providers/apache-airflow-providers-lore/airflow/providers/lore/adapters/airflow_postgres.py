from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any

from lore_splitter.storage.postgres import PostgresTableToastStore


class AirflowPostgresStorageError(RuntimeError):
    """Raised when Airflow PostgresHook storage cannot be initialized."""


@dataclass(frozen=True)
class PostgresHookTableToastStoreFactory:
    """Build a Postgres table TOAST store from an Airflow PostgresHook connection."""

    postgres_conn_id: str

    def build(self) -> PostgresTableToastStore:
        hook = _build_postgres_hook(self.postgres_conn_id)
        return PostgresTableToastStore(hook.get_conn())


def _build_postgres_hook(postgres_conn_id: str) -> Any:
    try:
        module = importlib.import_module("airflow.providers.postgres.hooks.postgres")
        hook_class = module.PostgresHook
    except Exception as exc:  # noqa: BLE001 - surface missing/invalid provider cleanly.
        raise AirflowPostgresStorageError(
            "PostgresHook is required for Airflow table TOAST storage; "
            "install apache-airflow-providers-postgres"
        ) from exc
    return hook_class(postgres_conn_id=postgres_conn_id)
