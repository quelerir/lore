"""Airflow boundary for one durable v1.2 Lore Splitter file run."""

from __future__ import annotations

import hashlib
import importlib
import json
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from airflow.exceptions import AirflowException, AirflowFailException
from airflow.models import BaseOperator
from lore_splitter.airflow_item import AirbyteItemError, normalize_airbyte_item
from lore_splitter.per_file import ProcessingAlreadyActive, redact_text
from lore_splitter.per_file_execution import (
    DurableExecutionResult,
    PerFileExecutionService,
    build_v12_dispatcher,
)
from airflow.utils.context import Context


class RetryableSplitterError(AirflowException):
    """Transient source, database, or provider failure."""


@dataclass(frozen=True)
class SplitterRuntimeAdapters:
    """Injectable leaves below the one v1.2 execution service boundary."""

    source_hook_factory: Callable[[dict[str, Any]], Any]
    repository_factory: Callable[[dict[str, Any]], Any]
    table_store_factory: Callable[[dict[str, Any]], Any]
    image_store_factory: Callable[[dict[str, Any]], Any]
    dispatch_factory: Callable[[dict[str, Any]], Callable[..., Any]]


def _s3_hook(conn_id: str) -> Any:
    try:
        return importlib.import_module("airflow.providers.amazon.aws.hooks.s3").S3Hook(
            aws_conn_id=conn_id
        )
    except Exception as exc:  # noqa: BLE001
        raise AirflowException("S3 hook is unavailable") from exc


def _postgres_connection(conn_id: str) -> Any:
    try:
        hook = importlib.import_module("airflow.providers.postgres.hooks.postgres").PostgresHook(
            postgres_conn_id=conn_id
        )
        return hook.get_conn()
    except Exception as exc:  # noqa: BLE001
        raise AirflowException("Postgres hook is unavailable") from exc


def _download(hook: Any, *, bucket: str, key: str, destination: Path) -> bytes:
    try:
        if hasattr(hook, "get_key"):
            obj = hook.get_key(key=key, bucket_name=bucket)
            return obj.get()["Body"].read()
        if hasattr(hook, "download_file"):
            hook.download_file(key=key, bucket_name=bucket, local_path=str(destination))
            return destination.read_bytes()
        if hasattr(hook, "read_key"):
            value = hook.read_key(key=key, bucket_name=bucket)
            return value.encode("utf-8") if isinstance(value, str) else bytes(value)
    except Exception as exc:  # noqa: BLE001
        raise RetryableSplitterError("source download failed") from exc
    raise AirflowFailException("S3 hook cannot read source objects")


def _default_runtime_adapters() -> SplitterRuntimeAdapters:
    from airflow.providers.lore.adapters.airflow_postgres import (
        PostgresHookTableToastStoreFactory,
    )
    from airflow.providers.lore.adapters.airflow_s3 import S3HookObjectToastStore
    from lore_splitter.storage.core_repository import CoreRepository

    return SplitterRuntimeAdapters(
        source_hook_factory=lambda config: _s3_hook(str(config["s3_conn_id"])),
        repository_factory=lambda config: CoreRepository(
            _postgres_connection(str(config["postgres_conn_id"]))
        ),
        table_store_factory=lambda config: PostgresHookTableToastStoreFactory(
            str(config["postgres_conn_id"])
        ).build(),
        image_store_factory=lambda config: S3HookObjectToastStore(
            s3_conn_id=str(config["s3_conn_id"])
        ),
        dispatch_factory=lambda _config: build_v12_dispatcher(),
    )


def _build_execution_service(
    config: dict[str, Any], *, adapters: SplitterRuntimeAdapters | None = None
) -> PerFileExecutionService:
    from lore_splitter.storage.persistence import PersistenceCoordinator

    postgres_conn_id = str(config.get("postgres_conn_id") or "")
    if adapters is None and not postgres_conn_id:
        raise AirflowFailException("missing required splitter key: postgres_conn_id")
    adapters = adapters or _default_runtime_adapters()
    repository = adapters.repository_factory(config)
    table_store = adapters.table_store_factory(config)
    image_store = adapters.image_store_factory(config)
    return PerFileExecutionService(
        repository=repository,
        coordinator=PersistenceCoordinator(
            repository, table_store=table_store, object_store=image_store
        ),
        dispatch=adapters.dispatch_factory(config),
        operator_version="lore-splitter/v1.2",
    )


def _compact_xcom(result: DurableExecutionResult, *, file_id: str) -> dict[str, Any]:
    return {
        "file_id": file_id,
        "run_id": result.run_id,
        "status": result.status.value,
        "pipeline_type": result.pipeline_type,
        "counts": {"chunks": result.chunk_count, "payloads": result.payload_count,
                   "warnings": result.warning_count, "errors": result.error_count},
        "schema_identities": {"operator_version": "lore-splitter/v1.2"},
    }


def _claim_context(context: Context, *, fallback_task_id: str | None) -> tuple[Any, str]:
    task_instance = context.get("ti") or context.get("task_instance")
    if task_instance is None or not callable(getattr(task_instance, "xcom_push", None)):
        raise AirflowFailException("mapped task instance context is required")
    dag_id = str(getattr(task_instance, "dag_id", "") or "")
    run_id = str(context.get("run_id") or getattr(task_instance, "run_id", "") or "")
    task_id = str(getattr(task_instance, "task_id", "") or fallback_task_id or "")
    map_index = getattr(task_instance, "map_index", None)
    if not dag_id or not run_id or not task_id or type(map_index) is not int:
        raise AirflowFailException("complete mapped task coordinates are required")
    canonical = json.dumps(
        [dag_id, run_id, task_id, map_index],
        ensure_ascii=True,
        separators=(",", ":"),
    )
    return task_instance, hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class LoreSplitterOperator(BaseOperator):
    """Normalize, acquire, and delegate exactly one raw Airbyte file item."""

    template_fields = ("file_item", "configurations", "overwrite", "s3_conn_id")

    def __init__(
        self,
        *,
        file_item: dict[str, Any],
        configurations: dict[str, Any],
        overwrite: bool = False,
        s3_conn_id: str | None = None,
        runtime_adapters: SplitterRuntimeAdapters | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.file_item = file_item
        self.configurations = configurations
        self.overwrite = bool(overwrite)
        self.s3_conn_id = s3_conn_id
        self.runtime_adapters = runtime_adapters

    def execute(self, context: Context) -> dict[str, Any]:
        try:
            item = normalize_airbyte_item(self.file_item)
            config = dict(self.configurations)
            task_instance, orchestration_claim_key = _claim_context(
                context, fallback_task_id=self.task_id
            )
            if self.s3_conn_id is not None and config.get("s3_conn_id") != self.s3_conn_id:
                raise AirbyteItemError(
                    "configured s3 connection does not match resolved configuration"
                )
        except AirbyteItemError as exc:
            raise AirflowFailException(redact_text(str(exc))) from exc

        scratch = Path(tempfile.mkdtemp(prefix="lore-splitter-"))
        try:
            source_path = scratch / "source"
            adapters = self.runtime_adapters or _default_runtime_adapters()
            source_bytes = _download(
                adapters.source_hook_factory(config),
                bucket=item.bucket,
                key=item.key,
                destination=source_path,
            )
            source_path.write_bytes(source_bytes)
            result = _build_execution_service(config, adapters=adapters).execute(
                item.source_file,
                source_bytes,
                config,
                overwrite=self.overwrite,
                orchestration_claim_key=orchestration_claim_key,
                on_run_claimed=lambda run_id: task_instance.xcom_push(
                    key="lore_run_claim",
                    value={"schema_version": "lore/run-claim/v1", "run_id": run_id},
                ),
            )
            return _compact_xcom(result, file_id=item.source_file.file_id)
        except AirflowFailException:
            raise
        except ProcessingAlreadyActive as exc:
            raise RetryableSplitterError("equivalent file is already processing") from exc
        except RetryableSplitterError:
            raise
        except PermissionError as exc:
            raise AirflowFailException(redact_text(str(exc))) from exc
        except (OSError, ConnectionError, TimeoutError) as exc:
            raise RetryableSplitterError("transient Splitter dependency failure") from exc
        except Exception as exc:  # deterministic lane/input failures are non-retryable.
            raise AirflowFailException(redact_text(str(exc))) from exc
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
