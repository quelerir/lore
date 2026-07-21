from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from _airflow_stubs import install_airflow_stubs

PROVIDER_ROOT = Path(__file__).resolve().parents[1]
FAKE_PASSWORD = "secret-password"


def import_operator_module():
    install_airflow_stubs()
    sys.modules.pop("airflow.providers.lore.operators.lore_splitter_operator", None)
    sys.path.insert(0, str(PROVIDER_ROOT))
    try:
        return importlib.import_module("airflow.providers.lore.operators.lore_splitter_operator")
    finally:
        sys.path.remove(str(PROVIDER_ROOT))


def file_item(**overrides):
    value = {
        "source_id": "drive",
        "stream": "regulations",
        "file_id": "file-1",
        "source_path": "Reports/readme.md",
        "object_path": "Reports/readme.md",
        "mime_type": "text/markdown",
        "size_bytes": 12,
        "bucket": "source-bucket",
        "key": "staging/readme.md",
    }
    value.update(overrides)
    return value


def config(**overrides):
    value = {
        "s3_conn_id": "shared",
        "postgres_conn_id": "core",
        "image_toast_bucket": "lore-images",
        "image_toast_prefix": "splitter/images",
        "storage_schema": "lore_core",
        "storage_mode": "dry_run",
        "embedding_byte_budget": 4096,
        "max_embedding_unique_values": 3,
        "toast_min_rows": 40,
        "toast_min_columns": 8,
        "toast_min_cells": 240,
    }
    value.update(overrides)
    return value


def test_operator_templates_s3_connection_id_from_dag_configuration():
    module = import_operator_module()

    assert "s3_conn_id" in module.LoreSplitterOperator.template_fields


def test_download_prefers_binary_s3_object_api():
    module = import_operator_module()
    body = Mock()
    body.read.return_value = b"\x91\x92binary-docx"
    hook = SimpleNamespace(
        read_key=Mock(side_effect=UnicodeDecodeError("utf-8", b"\x91", 0, 1, "binary")),
        get_key=Mock(return_value=SimpleNamespace(get=Mock(return_value={"Body": body}))),
    )

    assert module._download(hook, bucket="lore-files", key="source.docx", destination=Path("/tmp/source")) == b"\x91\x92binary-docx"
    hook.read_key.assert_not_called()
    hook.get_key.assert_called_once_with(key="source.docx", bucket_name="lore-files")


@dataclass
class FakeRepository:
    finalized: list[dict]
    error: Exception | None = None
    orchestration_claim_key: str | None = None

    def claim(
        self,
        _source,
        _identity,
        *,
        overwrite=False,
        orchestration_claim_key=None,
    ):
        self.overwrite = overwrite
        self.orchestration_claim_key = orchestration_claim_key
        return "run-1"

    def finalize_persisted(self, run_id, **kwargs):
        if self.error:
            raise self.error
        self.finalized.append({"run_id": run_id, **kwargs})
        from lore_splitter.per_file import RunResult

        counts = kwargs["counts"]
        return RunResult(
            run_id,
            kwargs["status"],
            chunk_count=counts["chunk_count"],
            payload_count=counts["payload_count"],
        )


class FakeObjectStore:
    def __init__(self):
        self.plans = []

    def store_object(self, plan):
        self.plans.append(plan)
        from lore_splitter.storage import ImageToastStorageResult

        return ImageToastStorageResult(
            toast_id=plan.toast_id,
            bucket=plan.bucket,
            object_key=plan.object_key,
            content_type=getattr(plan, "content_type", "image/png"),
            extension=getattr(plan, "extension", ".png"),
            byte_size=getattr(plan, "byte_size", 1),
            checksum_sha256=plan.checksum_sha256,
            action="created",
            source=getattr(plan, "source", None),
            source_kind=getattr(plan, "source_kind", "document"),
            source_checksum=getattr(plan, "source_checksum", plan.checksum_sha256),
            source_location=plan.source_location,
        )


class FakeTableStore:
    def store_table(self, plan):
        from lore_splitter.storage import TableToastStorageResult

        return TableToastStorageResult.from_plan(plan, action="created")


class FakeSource:
    def __init__(self, payload=b"# Readme\n\ncontent", error=None):
        self.payload = payload
        self.error = error
        self.calls = []

    def read_key(self, *, key, bucket_name):
        self.calls.append((bucket_name, key))
        if self.error:
            raise self.error
        return self.payload


class FakeTaskInstance:
    def __init__(
        self,
        *,
        dag_id="lore_splitter",
        run_id="scheduled__2026-07-15T00:00:00+00:00",
        task_id="split_file",
        map_index=0,
    ):
        self.dag_id = dag_id
        self.run_id = run_id
        self.task_id = task_id
        self.map_index = map_index
        self.pushes = []

    def xcom_push(self, *, key, value):
        self.pushes.append((key, value))


def airflow_context(**overrides):
    ti = FakeTaskInstance(**overrides)
    return {"ti": ti, "run_id": ti.run_id}


def runtime_adapters(module, *, source, repository, image_store, dispatch):
    return module.SplitterRuntimeAdapters(
        source_hook_factory=lambda _config: source,
        repository_factory=lambda _config: repository,
        table_store_factory=lambda _config: FakeTableStore(),
        image_store_factory=lambda _config: image_store,
        dispatch_factory=lambda _config: dispatch,
    )


def test_operator_uses_one_raw_item_and_returns_compact_xcom_through_real_service():
    module = import_operator_module()
    from lore_splitter.chunks import build_chunk
    from lore_splitter.per_file_execution import LaneResult

    source = FakeSource()
    repository = FakeRepository([])
    image_store = FakeObjectStore()

    def dispatch(source_file, source_bytes, run_id, resolved_config):
        assert source_bytes == b"# Readme\n\ncontent"
        assert resolved_config["s3_conn_id"] == "shared"
        return LaneResult(
            "markdown",
            chunks=(
                build_chunk(
                    run_id=run_id,
                    file_id=source_file.file_id,
                    ordinal=0,
                    pipeline_type="markdown",
                    chunk_type="text",
                    display_text="# Readme",
                    vector_text="# Readme",
                    fulltext="# Readme",
                ),
            ),
        )

    operator = module.LoreSplitterOperator(
        task_id="split_file",
        file_item=file_item(),
        configurations=config(),
        overwrite=False,
        runtime_adapters=runtime_adapters(
            module,
            source=source,
            repository=repository,
            image_store=image_store,
            dispatch=dispatch,
        ),
    )
    context = airflow_context()
    result = operator.execute(context)

    assert source.calls == [("source-bucket", "staging/readme.md")]
    assert repository.finalized[0]["counts"] == {
        "chunk_count": 1,
        "payload_count": 0,
        "warning_count": 0,
        "error_count": 0,
    }
    assert result["file_id"] == "file-1"
    assert result["status"] == "success"
    assert "/secret/path" not in str(result)
    assert "artifact_paths" not in result
    assert "# Readme" not in str(result)
    assert operator.overwrite is False
    assert context["ti"].pushes == [
        (
            "lore_run_claim",
            {"schema_version": "lore/run-claim/v1", "run_id": "run-1"},
        )
    ]
    assert repository.orchestration_claim_key is not None
    assert len(repository.orchestration_claim_key) == 64


def test_operator_persists_typed_table_registration_through_real_service():
    module = import_operator_module()
    from lore_splitter.per_file_execution import LaneResult

    plan = SimpleNamespace(
        toast_id="toast_table_1",
        schema_name="lore_toast",
        table_name="toast_table_1",
        row_count=1,
        warnings=(),
        diagnostics=(),
        source={"file_id": "file-1"},
        source_kind="workbook",
        source_checksum="a" * 64,
        source_location={"sheet": "Sheet1", "range": "A1"},
        workbook_checksum="a" * 64,
        sheet={"name": "Sheet1"},
        range={"a1": "A1"},
    )
    repository = FakeRepository([])
    operator = module.LoreSplitterOperator(
        task_id="split_file",
        file_item=file_item(source_path="Reports/data.xlsx", mime_type="application/xlsx"),
        configurations=config(),
        runtime_adapters=runtime_adapters(
            module,
            source=FakeSource(b"PK\x03\x04workbook"),
            repository=repository,
            image_store=FakeObjectStore(),
            dispatch=lambda *_args: LaneResult(
                "workbook",
                payloads=(
                    {
                        "payload_id": "toast_table_1",
                        "kind": "table",
                        "plan": plan,
                        "occurrence_ordinal": 0,
                        "storage_identity": "toast_table_1",
                        "content_hash": "a" * 64,
                        "coordinates": {"sheet": "Sheet1", "range": "A1"},
                        "metadata": {"columns": ["value"], "column_count": 1},
                    },
                ),
            ),
        ),
    )

    result = operator.execute(airflow_context())

    persisted = repository.finalized[0]
    registration = persisted["payloads"][0]["metadata"]["audit_registration"]
    assert result["status"] == "success"
    assert persisted["counts"] == {
        "chunk_count": 0,
        "payload_count": 1,
        "warning_count": 0,
        "error_count": 0,
    }
    assert registration["payload_id"] == "toast_table_1"
    assert registration["backend"] == "postgres"
    assert registration["registration_identity"]["schema_name"] == "lore_toast"
    assert registration["registration_identity"]["table_name"] == "toast_table_1"


def test_public_operator_has_no_legacy_pipeline_import_or_call():
    """The public Airflow boundary must use only the v1.2 execution service."""
    operator_source = (
        PROVIDER_ROOT
        / "airflow/providers/lore/operators/lore_splitter_operator.py"
    ).read_text(encoding="utf-8")

    assert "splitter.pipeline" not in operator_source
    assert "PipelineConfig" not in operator_source


def test_operator_maps_missing_contract_to_non_retryable_failure(monkeypatch):
    module = import_operator_module()
    operator = module.LoreSplitterOperator(
        task_id="split_file", file_item=file_item(file_id=""), configurations=config()
    )
    with pytest.raises(module.AirflowFailException, match="file identity"):
        operator.execute(airflow_context())


def test_operator_redacts_dsn_from_permanent_dispatch_failure():
    module = import_operator_module()
    source = FakeSource(b"# data")

    def dispatch(*_args):
        raise ValueError("postgresql://u:" + FAKE_PASSWORD + "@db/lore")

    context = airflow_context()
    with pytest.raises(module.AirflowFailException) as error:
        module.LoreSplitterOperator(
            task_id="split_file",
            file_item=file_item(),
            configurations=config(),
            runtime_adapters=runtime_adapters(
                module,
                source=source,
                repository=FakeRepository([]),
                image_store=FakeObjectStore(),
                dispatch=dispatch,
            ),
        ).execute(context)
    assert FAKE_PASSWORD not in str(error.value)
    assert "postgresql://" not in str(error.value)
    assert context["ti"].pushes == [
        (
            "lore_run_claim",
            {"schema_version": "lore/run-claim/v1", "run_id": "run-1"},
        )
    ]


def test_operator_retries_transient_source_and_postgres_failures():
    module = import_operator_module()
    from lore_splitter.per_file_execution import LaneResult

    for source, repository, dispatch in (
        (
            FakeSource(error=OSError("s3 unavailable")),
            FakeRepository([]),
            lambda *_args: LaneResult("markdown"),
        ),
        (
            FakeSource(),
            FakeRepository([], error=ConnectionError("postgres unavailable")),
            lambda *_args: LaneResult("markdown"),
        ),
        (
            FakeSource(),
            FakeRepository([]),
            lambda *_args: (_ for _ in ()).throw(TimeoutError("model")),
        ),
    ):
        with pytest.raises(module.RetryableSplitterError):
            module.LoreSplitterOperator(
                task_id="split_file",
                file_item=file_item(),
                configurations=config(),
                runtime_adapters=runtime_adapters(
                    module,
                    source=source,
                    repository=repository,
                    image_store=FakeObjectStore(),
                    dispatch=dispatch,
                ),
            ).execute(airflow_context())


@pytest.mark.parametrize(
    "failure",
    [
        ValueError("invalid lane configuration"),
        PermissionError("provider authentication rejected"),
        LookupError("unknown model"),
    ],
)
def test_operator_maps_invalid_auth_and_unknown_model_to_non_retryable_failure(failure):
    module = import_operator_module()

    def dispatch(*_args):
        raise failure

    with pytest.raises(module.AirflowFailException):
        module.LoreSplitterOperator(
            task_id="split_file",
            file_item=file_item(),
            configurations=config(),
            runtime_adapters=runtime_adapters(
                module,
                source=FakeSource(),
                repository=FakeRepository([]),
                image_store=FakeObjectStore(),
                dispatch=dispatch,
            ),
        ).execute(airflow_context())


def test_operator_keeps_source_reads_out_of_configured_image_destination():
    module = import_operator_module()
    from lore_splitter.per_file_execution import LaneResult

    @dataclass(frozen=True)
    class ImagePlan:
        toast_id: str = "toast_img_1"
        bucket: str = "wrong-bucket"
        object_key: str = "original.png"
        checksum_sha256: str = "a" * 64
        source_location: dict = None

    source = FakeSource()
    repository = FakeRepository([])
    image_store = FakeObjectStore()
    operator = module.LoreSplitterOperator(
        task_id="split_file",
        file_item=file_item(bucket="airbyte-source", key="incoming/source.md"),
        configurations=config(image_toast_bucket="lore-images", image_toast_prefix="runs/17"),
        runtime_adapters=runtime_adapters(
            module,
            source=source,
            repository=repository,
            image_store=image_store,
            dispatch=lambda *_args: LaneResult(
                "markdown",
                payloads=(
                    {
                        "payload_id": "toast_img_1",
                        "kind": "image",
                        "plan": ImagePlan(source_location={}),
                        "occurrence_ordinal": 0,
                        "storage_identity": "toast_img_1",
                        "content_hash": "a" * 64,
                        "coordinates": {},
                        "metadata": {},
                    },
                ),
            ),
        ),
    )

    operator.execute(airflow_context())

    assert source.calls == [("airbyte-source", "incoming/source.md")]
    assert image_store.plans[0].bucket == "lore-images"
    assert image_store.plans[0].object_key == "runs/17/original.png"


def test_claim_owner_is_stable_for_same_coordinates_and_changes_by_map_index():
    module = import_operator_module()
    from lore_splitter.per_file_execution import LaneResult

    repositories = [FakeRepository([]) for _ in range(3)]
    contexts = [airflow_context(), airflow_context(), airflow_context(map_index=1)]
    for repository, context in zip(repositories, contexts, strict=True):
        module.LoreSplitterOperator(
            task_id="split_file",
            file_item=file_item(),
            configurations=config(),
            runtime_adapters=runtime_adapters(
                module,
                source=FakeSource(),
                repository=repository,
                image_store=FakeObjectStore(),
                dispatch=lambda *_args: LaneResult("markdown"),
            ),
        ).execute(context)

    assert repositories[0].orchestration_claim_key == repositories[1].orchestration_claim_key
    assert repositories[0].orchestration_claim_key != repositories[2].orchestration_claim_key
    assert all(
        context["ti"].pushes
        == [
            (
                "lore_run_claim",
                {"schema_version": "lore/run-claim/v1", "run_id": "run-1"},
            )
        ]
        for context in contexts
    )


def test_pre_claim_download_failure_pushes_no_claim_xcom():
    module = import_operator_module()
    from lore_splitter.per_file_execution import LaneResult

    context = airflow_context()
    with pytest.raises(module.RetryableSplitterError):
        module.LoreSplitterOperator(
            task_id="split_file",
            file_item=file_item(),
            configurations=config(),
            runtime_adapters=runtime_adapters(
                module,
                source=FakeSource(error=OSError("s3 unavailable")),
                repository=FakeRepository([]),
                image_store=FakeObjectStore(),
                dispatch=lambda *_args: LaneResult("markdown"),
            ),
        ).execute(context)

    assert context["ti"].pushes == []


def test_retry_after_xcom_clear_republishes_and_finishes_same_active_run():
    module = import_operator_module()
    from lore_splitter.per_file import (
        ProcessingAlreadyActive,
        RunResult,
        RunStatus,
    )
    from lore_splitter.per_file_execution import LaneResult

    class StatefulRepository:
        def __init__(self):
            self.owner = None
            self.status = RunStatus.ACTIVE

        def claim(self, source, _identity, *, overwrite=False, orchestration_claim_key=None):
            del overwrite
            if self.owner is None:
                self.owner = orchestration_claim_key
            elif self.owner != orchestration_claim_key:
                raise ProcessingAlreadyActive(
                    f"{source.source_id}:{source.stream}:{source.file_id}", "run-durable"
                )
            if self.status is RunStatus.ACTIVE:
                return "run-durable"
            return RunResult("run-durable", self.status, reused=True)

        def finalize_persisted(self, run_id, **kwargs):
            self.status = kwargs["status"]
            return RunResult(run_id, self.status)

    repository = StatefulRepository()
    attempts = 0

    def dispatch(*_args):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ConnectionError("transient lane failure")
        return LaneResult("markdown")

    operator = module.LoreSplitterOperator(
        task_id="split_file",
        file_item=file_item(),
        configurations=config(),
        runtime_adapters=runtime_adapters(
            module,
            source=FakeSource(),
            repository=repository,
            image_store=FakeObjectStore(),
            dispatch=dispatch,
        ),
    )
    first_context = airflow_context()
    with pytest.raises(module.RetryableSplitterError):
        operator.execute(first_context)
    assert first_context["ti"].pushes[-1][1]["run_id"] == "run-durable"
    assert repository.status is RunStatus.ACTIVE

    retry_context = airflow_context()  # new TI state simulates Airflow clearing XCom
    result = operator.execute(retry_context)
    assert retry_context["ti"].pushes == [
        (
            "lore_run_claim",
            {"schema_version": "lore/run-claim/v1", "run_id": "run-durable"},
        )
    ]
    assert result["run_id"] == "run-durable"
    assert result["status"] == "success"
    assert repository.status is RunStatus.SUCCESS

    other_map_context = airflow_context(map_index=1)
    with pytest.raises(module.RetryableSplitterError):
        operator.execute(other_map_context)
    assert other_map_context["ti"].pushes == []
