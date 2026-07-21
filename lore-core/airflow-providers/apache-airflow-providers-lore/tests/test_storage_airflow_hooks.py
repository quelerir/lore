from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
from lore_splitter.storage import StoragePlanError
from lore_splitter.storage.object_schema import image_object_key
from _airflow_stubs import install_airflow_stubs
from _storage_plans import _image_plan, _storage_plan

PROVIDER_ROOT = Path(__file__).resolve().parents[1]


def _import_storage_module(module_name: str):
    install_airflow_stubs()
    sys.modules.pop(module_name, None)
    sys.path.insert(0, str(PROVIDER_ROOT))
    try:
        return importlib.import_module(module_name)
    finally:
        sys.path.remove(str(PROVIDER_ROOT))


def test_s3hook_object_store_uploads_plan_key_unchanged() -> None:
    module = _import_storage_module("airflow.providers.lore.adapters.airflow_s3")
    s3_hook = sys.modules["airflow.providers.amazon.aws.hooks.s3"].S3Hook(
        aws_conn_id="lore_splitter_s3"
    )
    plan = _image_plan()

    result = module.S3HookObjectToastStore(
        s3_hook=s3_hook,
        prefix="tenant-a/images",
    ).store_object(plan)

    s3_hook.load_bytes.assert_called_once_with(
        bytes_data=plan.payload,
        key=plan.object_key,
        bucket_name=plan.bucket,
        replace=True,
    )
    assert result.action == "created"
    assert result.bucket == plan.bucket
    assert result.object_key == plan.object_key
    assert result.checksum_sha256 == plan.checksum_sha256


def test_s3hook_object_store_uploads_pipeline_prefixed_plan_key_once() -> None:
    module = _import_storage_module("airflow.providers.lore.adapters.airflow_s3")
    s3_hook = sys.modules["airflow.providers.amazon.aws.hooks.s3"].S3Hook(
        aws_conn_id="lore_splitter_s3"
    )
    plan = _image_plan()
    prefixed_plan = plan.__class__(
        **{
            **plan.to_constructor_dict(),
            "object_key": image_object_key(
                plan.toast_id,
                plan.extension,
                prefix="tenant-a/images",
            ),
        }
    )

    result = module.S3HookObjectToastStore(s3_hook=s3_hook).store_object(prefixed_plan)

    s3_hook.load_bytes.assert_called_once_with(
        bytes_data=plan.payload,
        key=prefixed_plan.object_key,
        bucket_name=plan.bucket,
        replace=True,
    )
    assert result.action == "created"
    assert result.object_key == prefixed_plan.object_key


def test_s3hook_object_store_does_not_double_default_image_toast_prefix() -> None:
    module = _import_storage_module("airflow.providers.lore.adapters.airflow_s3")
    s3_hook = sys.modules["airflow.providers.amazon.aws.hooks.s3"].S3Hook(
        aws_conn_id="lore_splitter_s3"
    )
    plan = _image_plan()

    result = module.S3HookObjectToastStore(s3_hook=s3_hook).store_object(plan)

    s3_hook.load_bytes.assert_called_once_with(
        bytes_data=plan.payload,
        key=plan.object_key,
        bucket_name=plan.bucket,
        replace=True,
    )
    assert result.object_key == plan.object_key


def test_s3hook_object_store_upload_failure_returns_bounded_failed_result() -> None:
    module = _import_storage_module("airflow.providers.lore.adapters.airflow_s3")
    s3_hook = sys.modules["airflow.providers.amazon.aws.hooks.s3"].S3Hook(
        aws_conn_id="lore_splitter_s3"
    )
    s3_hook.load_bytes = Mock(side_effect=RuntimeError("boom with secret-token"))
    plan = _image_plan()

    result = module.S3HookObjectToastStore(s3_hook=s3_hook).store_object(plan)

    assert result.action == "failed"
    assert result.bucket == plan.bucket
    assert result.object_key == plan.object_key
    assert "secret-token" not in " ".join(result.diagnostics)
    assert any("s3_upload_failed" in diagnostic for diagnostic in result.diagnostics)


def test_s3hook_object_store_rejects_invalid_plan_before_upload() -> None:
    module = _import_storage_module("airflow.providers.lore.adapters.airflow_s3")
    s3_hook = sys.modules["airflow.providers.amazon.aws.hooks.s3"].S3Hook(
        aws_conn_id="lore_splitter_s3"
    )
    plan = _image_plan()
    tampered = plan.__class__(
        **{
            **plan.to_constructor_dict(),
            "byte_size": plan.byte_size + 1,
        }
    )

    with pytest.raises(StoragePlanError):
        module.S3HookObjectToastStore(s3_hook=s3_hook).store_object(tampered)

    s3_hook.load_bytes.assert_not_called()


def test_postgreshook_table_store_factory_wraps_hook_connection(monkeypatch) -> None:
    module = _import_storage_module("airflow.providers.lore.adapters.airflow_postgres")
    fake_store = Mock()
    fake_store_cls = Mock(return_value=fake_store)
    monkeypatch.setattr(module, "PostgresTableToastStore", fake_store_cls)

    store = module.PostgresHookTableToastStoreFactory(
        postgres_conn_id="lore_splitter_postgres"
    ).build()

    postgres_hook = sys.modules[
        "airflow.providers.postgres.hooks.postgres"
    ].PostgresHook.instances[-1]
    assert postgres_hook.postgres_conn_id == "lore_splitter_postgres"
    postgres_hook.get_conn.assert_called_once_with()
    fake_store_cls.assert_called_once_with(postgres_hook.connection)
    assert store is fake_store


def test_postgreshook_table_store_factory_can_store_with_wrapped_store(monkeypatch) -> None:
    module = _import_storage_module("airflow.providers.lore.adapters.airflow_postgres")
    plan = _storage_plan()

    class FakeWrappedStore:
        def __init__(self, connection):
            self.connection = connection

        def store_table(self, storage_plan):
            return storage_plan

    monkeypatch.setattr(module, "PostgresTableToastStore", FakeWrappedStore)

    store = module.PostgresHookTableToastStoreFactory(
        postgres_conn_id="lore_splitter_postgres"
    ).build()

    assert store.store_table(plan) is plan
