from __future__ import annotations

import hashlib
from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from lore_splitter.chunks import build_chunk
from lore_splitter.contracts import SourceFile
from lore_splitter.documents import chunking as document_chunking
from lore_splitter.documents.conversion import DocumentMarkdownConverter
from lore_splitter.per_file import RunResult, RunStatus
from lore_splitter.per_file_execution import (
    LaneResult,
    PerFileExecutionService,
    _payload_entries,
    build_v12_dispatcher,
)


def _source() -> SourceFile:
    return SourceFile(
        source_id="drive",
        stream="regulations",
        file_id="file-1",
        source_path="readme.md",
        object_path="readme.md",
        mime_type="text/markdown",
        size_bytes=8,
    )


@dataclass
class _Repository:
    claimed: list[tuple[SourceFile, object, bool]]

    def claim(self, source, identity, *, overwrite=False):
        self.claimed.append((source, identity, overwrite))
        return "run-1"


@dataclass
class _Coordinator:
    calls: list[dict]

    def persist(self, run_id, chunks, payloads, *, logical_file_key, diagnostics, status):
        self.calls.append(
            {
                "run_id": run_id,
                "chunks": chunks,
                "payloads": payloads,
                "logical_file_key": logical_file_key,
                "diagnostics": diagnostics,
                "status": status,
            }
        )
        return RunResult(run_id, status, chunk_count=len(chunks), payload_count=len(payloads))


def test_service_claims_dispatches_and_returns_durable_result():
    repository = _Repository([])
    coordinator = _Coordinator([])

    def dispatch(source, source_bytes, run_id, config):
        assert source.file_id == "file-1"
        assert source_bytes == b"# hello\n"
        assert run_id == "run-1"
        return LaneResult(
            pipeline_type="markdown",
            chunks=(
                build_chunk(
                    run_id=run_id,
                    file_id=source.file_id,
                    ordinal=0,
                    pipeline_type="markdown",
                    chunk_type="text",
                    display_text="# hello",
                    vector_text="# hello",
                    fulltext="# hello",
                ),
            ),
        )

    result = PerFileExecutionService(
        repository=repository,
        coordinator=coordinator,
        dispatch=dispatch,
        operator_version="operator/v1",
    ).execute(_source(), b"# hello\n", {"chunk": {"max_tokens": 10}})

    assert result.run_id == "run-1"
    assert result.status is RunStatus.SUCCESS
    assert result.pipeline_type == "markdown"
    assert coordinator.calls[0]["logical_file_key"] == "drive:regulations:file-1"
    assert coordinator.calls[0]["status"] is RunStatus.SUCCESS


def test_cache_hit_bypasses_lane_dispatch_and_persistence():
    class CachedRepository(_Repository):
        def claim(self, source, identity, *, overwrite=False):
            self.claimed.append((source, identity, overwrite))
            return RunResult("prior-run", RunStatus.SUCCESS, reused=True, chunk_count=2)

    repository = CachedRepository([])
    coordinator = _Coordinator([])

    def no_dispatch(*args):
        raise AssertionError("cache hit must bypass dispatch")

    result = PerFileExecutionService(
        repository=repository,
        coordinator=coordinator,
        dispatch=no_dispatch,
        operator_version="operator/v1",
    ).execute(_source(), b"# hello\n", {"chunk": {"max_tokens": 10}})

    assert result.reused is True
    assert result.run_id == "prior-run"
    assert coordinator.calls == []


def test_skipped_lane_is_finalized_and_returns_durable_terminal_result():
    repository = _Repository([])
    coordinator = _Coordinator([])

    def dispatch(*args):
        return LaneResult(pipeline_type="unsupported", status=RunStatus.SKIPPED)

    result = PerFileExecutionService(
        repository=repository,
        coordinator=coordinator,
        dispatch=dispatch,
        operator_version="operator/v1",
    ).execute(_source(), b"# hello\n", {"chunk": {"max_tokens": 10}})

    assert result.status is RunStatus.SKIPPED
    assert coordinator.calls[0]["status"] is RunStatus.SKIPPED
    assert coordinator.calls[0]["logical_file_key"] == "drive:regulations:file-1"


def test_persistence_failure_never_returns_success_result():
    class FailingCoordinator(_Coordinator):
        def persist(self, *args, **kwargs):
            raise RuntimeError("core unavailable")

    def dispatch(*args):
        return LaneResult(pipeline_type="markdown")

    with pytest.raises(RuntimeError, match="core unavailable"):
        PerFileExecutionService(
            repository=_Repository([]),
            coordinator=FailingCoordinator([]),
            dispatch=dispatch,
            operator_version="operator/v1",
        ).execute(_source(), b"# hello\n", {"chunk": {"max_tokens": 10}})


def test_deterministic_dispatch_failure_is_durably_finalized_before_reraise():
    repository = _Repository([])
    coordinator = _Coordinator([])

    def dispatch(*args):
        raise ValueError("invalid source")

    with pytest.raises(ValueError, match="invalid source"):
        PerFileExecutionService(
            repository=repository,
            coordinator=coordinator,
            dispatch=dispatch,
            operator_version="operator/v1",
        ).execute(_source(), b"# hello\n", {"chunk": {"max_tokens": 10}})

    assert coordinator.calls[0]["status"] is RunStatus.FAILED
    assert coordinator.calls[0]["chunks"] == []
    assert coordinator.calls[0]["payloads"] == []
    assert coordinator.calls[0]["diagnostics"][0].code == "deterministic_processing_failure"


def test_payload_plan_conversion_preserves_kind_identity_and_plan():
    @dataclass
    class TablePlan:
        toast_id: str = "toast_tbl_123"
        table_name: str = "toast_tbl_123"
        source_location: dict = None
        source_checksum: str = "a" * 64
        content_signature: str = "b" * 64

    plan = TablePlan(source_location={"sheet": "Data"})
    assert _payload_entries((plan,)) == (
        {
            "payload_id": "toast_tbl_123",
            "kind": "table",
            "plan": plan,
            "storage_identity": "toast_tbl_123",
            "content_hash": "b" * 64,
            "occurrence_ordinal": 0,
            "coordinates": {"sheet": "Data"},
            "metadata": {},
        },
    )


@pytest.mark.parametrize(
    "signature_attributes",
    [
        {},
        {"content_signature": ""},
        {"content_signature": "B" * 64},
        {"content_signature": "g" * 64},
        {"content_signature": "b" * 63},
    ],
    ids=["missing", "empty", "uppercase", "non-hex", "wrong-length"],
)
def test_table_payload_conversion_rejects_missing_or_malformed_content_signature(
    signature_attributes,
):
    plan = SimpleNamespace(
        toast_id="toast_tbl_123",
        table_name="toast_tbl_123",
        source_location={"sheet": "Data"},
        source_checksum="a" * 64,
        **signature_attributes,
    )

    with pytest.raises(ValueError, match="content_signature"):
        _payload_entries((plan,))


def test_image_payload_conversion_uses_payload_checksum_not_source_lineage():
    @dataclass
    class ImagePlan:
        toast_id: str = "toast_img_123"
        source_location: dict = None
        source_checksum: str = "a" * 64
        checksum_sha256: str = "b" * 64

    plan = ImagePlan(source_location={"page": 1})

    assert _payload_entries((plan,))[0]["content_hash"] == "b" * 64


def test_markdown_dispatch_uses_content_signature_for_table_payload():
    content = (
        "| name | value |\n| --- | --- |\n"
        + "".join(f"| row-{index} | {index} |\n" for index in range(60))
    ).encode()
    source = SourceFile(
        source_id="drive",
        stream="regulations",
        file_id="google-markdown-id",
        source_path="table.md",
        object_path="table.md",
        mime_type="text/markdown",
        size_bytes=len(content),
    )

    result = build_v12_dispatcher()(source, content, "run-1", {})

    payload = result.payloads[0]
    assert payload["content_hash"] == payload["plan"].content_signature
    assert payload["content_hash"] != hashlib.sha256(content).hexdigest()


def test_docx_dispatch_passes_converted_document_checksum(monkeypatch):
    converted_checksum = "b" * 64
    captured = {}

    def convert(_self, _document):
        return SimpleNamespace(markdown="# Converted", document_checksum=converted_checksum)

    def build_chunks(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(chunks=(), payload_plans=(), diagnostics=())

    monkeypatch.setattr(DocumentMarkdownConverter, "convert", convert)
    monkeypatch.setattr(document_chunking, "build_document_chunks", build_chunks)
    content = b"PK\x03\x04docx"
    source = SourceFile(
        source_id="drive",
        stream="regulations",
        file_id="google-docx-id",
        source_path="table.docx",
        object_path="table.docx",
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        size_bytes=len(content),
    )

    build_v12_dispatcher()(source, content, "run-1", {})

    assert captured["document_checksum"] == converted_checksum
