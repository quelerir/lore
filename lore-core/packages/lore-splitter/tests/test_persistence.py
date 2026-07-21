import pytest
from lore_audit.registration import PAYLOAD_REGISTRATION_V1
from lore_splitter.chunks import build_chunk
from lore_splitter.per_file import Diagnostic, RunResult, RunStatus
from lore_core_domain.storage_contracts import (
    ImageToastStorageResult,
    TableToastStorageResult,
)
from lore_splitter.storage.persistence import PersistenceCoordinator

SHA_A = "a" * 64
SHA_B = "b" * 64


class RecordingStore:
    def __init__(self, result) -> None:
        self.result = result
        self.calls = []

    def store_table(self, plan):
        self.calls.append(("table", plan))
        return self.result

    def store_object(self, plan):
        self.calls.append(("object", plan))
        return self.result


class RecordingRepository:
    def __init__(self) -> None:
        self.calls = []

    def finalize_persisted(self, run_id, **kwargs):
        self.calls.append((run_id, kwargs))
        return RunResult(
            run_id,
            kwargs["status"],
            chunk_count=kwargs["counts"]["chunk_count"],
            payload_count=kwargs["counts"]["payload_count"],
        )


def _chunk():
    return build_chunk(
        run_id="run-1",
        file_id="file-1",
        ordinal=0,
        pipeline_type="markdown",
        chunk_type="paragraph",
        display_text="A chunk",
        vector_text="A chunk",
        fulltext="A chunk",
    )


def table_result(action="created", **overrides):
    values = {
        "toast_id": "table-1",
        "schema_name": "lore_toast",
        "table_name": "toast_table_1",
        "row_count": 2,
        "action": action,
        "source_kind": "workbook",
        "source_checksum": SHA_A,
        "source_location": {"sheet": "Data", "range": "A1:B3"},
        "sheet": {"name": "Data"},
        "range": {"a1": "A1:B3"},
    }
    values.update(overrides)
    return TableToastStorageResult(**values)


def image_result(action="created", **overrides):
    values = {
        "toast_id": "image-1",
        "bucket": "lore-images",
        "object_key": "toast/image-1.png",
        "content_type": "image/png",
        "extension": ".png",
        "byte_size": 12,
        "checksum_sha256": SHA_B,
        "action": action,
        "source_kind": "document",
        "source_checksum": SHA_B,
        "source_location": {"paragraph": 3},
    }
    values.update(overrides)
    return ImageToastStorageResult(**values)


def test_coordinator_stores_payloads_before_one_core_finalization_and_returns_compact_summary():
    repository = RecordingRepository()
    table_store = RecordingStore(table_result())
    object_store = RecordingStore(image_result())
    coordinator = PersistenceCoordinator(
        repository,
        table_store=table_store,
        object_store=object_store,
    )
    payloads = [
        {
            "kind": "table",
            "payload_id": "table-1",
            "occurrence_ordinal": 0,
            "plan": {"table": "opaque"},
            "storage_identity": "table-1",
            "content_hash": SHA_A,
            "metadata": {
                "columns": ["employee", "amount"],
                "column_count": 2,
                "profile_signature": SHA_B,
                "unrelated": "retained",
            },
        },
        {
            "kind": "image",
            "payload_id": "image-1",
            "occurrence_ordinal": 1,
            "plan": {"payload": b"secret-bytes"},
            "storage_identity": "image-1",
            "content_hash": SHA_B,
            "metadata": {"width": 10, "height": 20},
        },
    ]

    result = coordinator.persist("run-1", [_chunk()], payloads, logical_file_key="drive:files:1")

    assert [kind for kind, _ in table_store.calls] == ["table"]
    assert [kind for kind, _ in object_store.calls] == ["object"]
    assert len(repository.calls) == 1
    run_id, kwargs = repository.calls[0]
    assert run_id == "run-1"
    assert kwargs["status"] is RunStatus.SUCCESS
    assert kwargs["counts"] == {
        "chunk_count": 1,
        "payload_count": 2,
        "warning_count": 0,
        "error_count": 0,
    }
    assert all(payload["verified"] for payload in kwargs["payloads"])
    assert all("plan" not in payload for payload in kwargs["payloads"])
    table, image = kwargs["payloads"]
    assert table["metadata"]["unrelated"] == "retained"
    assert table["metadata"]["audit_registration"]["schema_version"] == (
        PAYLOAD_REGISTRATION_V1
    )
    assert table["metadata"]["audit_registration"]["registration_identity"][
        "schema_name"
    ] == "lore_toast"
    assert image["metadata"]["audit_registration"]["registration_identity"] == {
        "bucket": "lore-images",
        "object_key": "toast/image-1.png",
        "content_type": "image/png",
        "extension": ".png",
        "byte_size": 12,
        "checksum_sha256": SHA_B,
        "source_kind": "document",
        "source_checksum": SHA_B,
        "source_location": {"paragraph": 3},
        "width": 10,
        "height": 20,
    }
    forwarded = repr(kwargs["payloads"])
    assert "secret-bytes" not in forwarded
    assert "opaque" not in forwarded
    assert result == RunResult("run-1", RunStatus.SUCCESS, chunk_count=1, payload_count=2)
    assert "secret-bytes" not in str(result)
    assert "opaque" not in str(result)


@pytest.mark.parametrize("action", ["failed", "collision"])
def test_payload_store_failure_is_fatal_and_never_finalizes_success(action):
    repository = RecordingRepository()
    table_store = RecordingStore(table_result(action))
    coordinator = PersistenceCoordinator(repository, table_store=table_store)

    with pytest.raises(ValueError, match="payload storage failed"):
        coordinator.persist(
            "run-1",
            [_chunk()],
            [
                {
                    "kind": "table",
                    "payload_id": "table-1",
                    "occurrence_ordinal": 0,
                    "plan": object(),
                }
            ],
            logical_file_key="drive:files:1",
        )

    assert repository.calls == []


def test_invalid_typed_result_never_crosses_core_finalization_boundary():
    repository = RecordingRepository()
    table_store = RecordingStore(table_result(toast_id="other-table"))
    coordinator = PersistenceCoordinator(repository, table_store=table_store)

    with pytest.raises(ValueError, match="invalid payload audit registration"):
        coordinator.persist(
            "run-1",
            [_chunk()],
            [
                {
                    "kind": "table",
                    "payload_id": "table-1",
                    "occurrence_ordinal": 0,
                    "plan": object(),
                    "content_hash": SHA_A,
                }
            ],
            logical_file_key="drive:files:1",
        )

    assert repository.calls == []


@pytest.mark.parametrize("status", [RunStatus.SKIPPED, RunStatus.FAILED])
def test_terminal_non_success_forwards_status_with_zero_durable_counts(status):
    repository = RecordingRepository()
    coordinator = PersistenceCoordinator(repository)

    result = coordinator.persist(
        "run-1", [], [], logical_file_key="drive:files:1", diagnostics=[], status=status
    )

    assert result.status is status
    assert result.chunk_count == 0
    assert result.payload_count == 0
    assert repository.calls[0][1]["status"] is status
    assert repository.calls[0][1]["counts"] == {
        "chunk_count": 0,
        "payload_count": 0,
        "warning_count": 0,
        "error_count": 0,
    }


def test_terminal_counters_match_forwarded_splitter_diagnostics():
    repository = RecordingRepository()
    coordinator = PersistenceCoordinator(repository)
    diagnostics = [
        Diagnostic("warning", "unsupported_format", "unsupported", "format"),
        Diagnostic("warning", "mime_mismatch", "mismatch", "format"),
        Diagnostic("error", "processing_failure", "failed", "dispatch"),
    ]

    coordinator.persist(
        "run-1",
        [],
        [],
        logical_file_key="drive:files:1",
        diagnostics=diagnostics,
        status=RunStatus.FAILED,
    )

    assert repository.calls[0][1]["counts"] == {
        "chunk_count": 0,
        "payload_count": 0,
        "warning_count": 2,
        "error_count": 1,
    }


def test_non_success_terminal_outcome_rejects_non_empty_chunks_before_finalization():
    repository = RecordingRepository()
    coordinator = PersistenceCoordinator(repository)

    with pytest.raises(ValueError, match="non-success terminal outcome"):
        coordinator.persist(
            "run-1", [_chunk()], [], logical_file_key="drive:files:1", status=RunStatus.FAILED
        )

    assert repository.calls == []
