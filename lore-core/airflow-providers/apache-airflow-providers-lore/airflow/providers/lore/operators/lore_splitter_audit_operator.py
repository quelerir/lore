"""Exact mapped run-claim handoff and deterministic Lore auditing."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any
from uuid import UUID

from airflow.exceptions import AirflowFailException
from airflow.models import BaseOperator
from airflow.providers.lore.adapters.airflow_audit_adapters import (
    AirflowAuditAdapters,
    build_airflow_audit_adapters,
)
from lore_audit.snapshot_repository import AuditReadBounds
from lore_audit.service import (
    AuditExecutionError,
    AuditService,
    AuditServiceResult,
)
from airflow.utils.context import Context

_CLAIM_SCHEMA_VERSION = "lore/run-claim/v1"
_NO_RUN = {"status": "no_run", "run_id": None}
_RESULT_KEYS = {
    "run_id",
    "ruleset_version",
    "status",
    "checked_rule_count",
    "outcome_counts",
    "severity_counts",
}
_MAX_COUNT_KEYS = 32
_MAX_COUNT = 1_000_000


class LoreSplitterAuditOperator(BaseOperator):
    """Audit only the matching Splitter map index's durable run claim."""

    template_fields = ("file_item",)

    def __init__(
        self,
        *,
        file_item: dict[str, Any],
        splitter_task_id: str,
        postgres_conn_id: str,
        s3_conn_id: str,
        ruleset_version: str = "audit/v1",
        audit_bounds: AuditReadBounds | None = None,
        adapter_factory: Callable[..., AirflowAuditAdapters] = build_airflow_audit_adapters,
        service_factory: Callable[..., AuditService] = AuditService,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        if (
            not isinstance(postgres_conn_id, str)
            or not postgres_conn_id
            or not isinstance(s3_conn_id, str)
            or not s3_conn_id
            or ruleset_version != "audit/v1"
            or not callable(adapter_factory)
            or not callable(service_factory)
        ):
            raise ValueError("audit operator configuration is invalid")
        bounds = audit_bounds if audit_bounds is not None else AuditReadBounds()
        if not isinstance(bounds, AuditReadBounds):
            raise ValueError("audit operator configuration is invalid")
        self.file_item = file_item
        self.splitter_task_id = splitter_task_id
        self.postgres_conn_id = postgres_conn_id
        self.s3_conn_id = s3_conn_id
        self.ruleset_version = ruleset_version
        self.audit_bounds = bounds
        self.adapter_factory = adapter_factory
        self.service_factory = service_factory

    def execute(self, context: Context) -> dict[str, Any]:
        task_instance = context.get("ti") or context.get("task_instance")
        map_index = getattr(task_instance, "map_index", None)
        if (
            task_instance is None
            or not callable(getattr(task_instance, "xcom_pull", None))
            or type(map_index) is not int
        ):
            return dict(_NO_RUN)

        claim = task_instance.xcom_pull(
            task_ids=self.splitter_task_id,
            key="lore_run_claim",
            map_indexes=map_index,
        )
        if not isinstance(claim, dict) or set(claim) != {"schema_version", "run_id"}:
            return dict(_NO_RUN)
        if claim["schema_version"] != _CLAIM_SCHEMA_VERSION or not isinstance(
            claim["run_id"], str
        ):
            return dict(_NO_RUN)
        try:
            run_id = str(UUID(claim["run_id"]))
        except (ValueError, AttributeError):
            return dict(_NO_RUN)

        try:
            adapters = self.adapter_factory(
                postgres_conn_id=self.postgres_conn_id,
                s3_conn_id=self.s3_conn_id,
                bounds=self.audit_bounds,
            )
            service = self.service_factory(
                reader=adapters.reader,
                writer=adapters.writer,
                bounds=adapters.bounds,
                payload_resolver=adapters.payload_resolver,
            )
        except Exception as exc:  # noqa: BLE001 - fixed public scheduler failure.
            raise AirflowFailException(
                "lore audit failed: dependency_initialization"
            ) from exc

        try:
            result = service.audit_run(run_id, self.ruleset_version)
        except AuditExecutionError as exc:
            raise AirflowFailException(f"lore audit failed: {exc.category}") from exc
        except Exception as exc:  # noqa: BLE001 - injected boundary must also fail closed.
            raise AirflowFailException("lore audit failed: unexpected_execution") from exc
        return self._safe_result(result, run_id)

    @staticmethod
    def _safe_result(result: AuditServiceResult, run_id: str) -> dict[str, Any]:
        try:
            projection = result.to_dict()
        except Exception as exc:  # noqa: BLE001 - never expose invalid result internals.
            raise AirflowFailException("lore audit failed: invalid_result") from exc
        if (
            not isinstance(projection, dict)
            or set(projection) != _RESULT_KEYS
            or projection["run_id"] != run_id
            or projection["ruleset_version"] != "audit/v1"
            or projection["status"] != "completed"
            or not LoreSplitterAuditOperator._valid_count(
                projection["checked_rule_count"]
            )
            or not LoreSplitterAuditOperator._valid_count_map(
                projection["outcome_counts"]
            )
            or not LoreSplitterAuditOperator._valid_count_map(
                projection["severity_counts"]
            )
        ):
            raise AirflowFailException("lore audit failed: invalid_result")
        return projection

    @staticmethod
    def _valid_count(value: Any) -> bool:
        return type(value) is int and 0 <= value <= _MAX_COUNT

    @staticmethod
    def _valid_count_map(value: Any) -> bool:
        return (
            isinstance(value, Mapping)
            and len(value) <= _MAX_COUNT_KEYS
            and all(
                isinstance(key, str)
                and 0 < len(key) <= 64
                and LoreSplitterAuditOperator._valid_count(count)
                for key, count in value.items()
            )
        )
