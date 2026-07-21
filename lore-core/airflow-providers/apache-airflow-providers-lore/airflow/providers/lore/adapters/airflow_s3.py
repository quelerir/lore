from __future__ import annotations

import importlib
from typing import Any

from lore_splitter.storage import (
    ImageToastStoragePlan,
    ImageToastStorageResult,
)
from lore_splitter.storage.object_schema import validate_image_storage_plan


class AirflowS3StorageError(RuntimeError):
    """Raised when Airflow S3Hook storage cannot be initialized."""


class S3HookObjectToastStore:
    """Object TOAST store backed by an Airflow S3Hook-compatible hook."""

    def __init__(
        self,
        *,
        s3_hook: Any | None = None,
        s3_conn_id: str | None = None,
        prefix: str = "",
    ) -> None:
        self.s3_hook = s3_hook if s3_hook is not None else _build_s3_hook(s3_conn_id)
        self.prefix = _normalize_prefix(prefix)

    def store_object(self, plan: ImageToastStoragePlan) -> ImageToastStorageResult:
        validate_image_storage_plan(plan)
        try:
            self.s3_hook.load_bytes(
                bytes_data=plan.payload,
                key=plan.object_key,
                bucket_name=plan.bucket,
                replace=True,
            )
        except Exception:  # noqa: BLE001 - storage failures are returned as diagnostics.
            return ImageToastStorageResult.from_plan(
                plan,
                action="failed",
                diagnostics=(*plan.diagnostics, "s3_upload_failed"),
            )
        return ImageToastStorageResult.from_plan(plan, action="created")


def _build_s3_hook(s3_conn_id: str | None) -> Any:
    try:
        module = importlib.import_module("airflow.providers.amazon.aws.hooks.s3")
        hook_class = module.S3Hook
    except Exception as exc:  # noqa: BLE001 - surface missing/invalid provider cleanly.
        raise AirflowS3StorageError(
            "S3Hook is required for Airflow image TOAST storage; "
            "install apache-airflow-providers-amazon"
        ) from exc
    return hook_class(aws_conn_id=s3_conn_id)


def _normalize_prefix(prefix: str) -> str:
    return str(prefix or "").strip("/")
