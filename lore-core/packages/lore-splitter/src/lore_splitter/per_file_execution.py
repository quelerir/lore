"""Airflow-independent orchestration for one durable Splitter file run."""

from __future__ import annotations

import hashlib
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from lore_splitter.chunks import CHUNK_SCHEMA_VERSION, Chunk
from lore_splitter.config import content_config_hash
from lore_splitter.contracts import SourceFile
from lore_splitter.per_file import (
    Diagnostic,
    RunResult,
    RunStatus,
    build_processing_identity,
    logical_file_key,
)


@dataclass(frozen=True)
class LaneResult:
    """Validated lane output before payload/core persistence."""

    pipeline_type: str
    chunks: tuple[Chunk, ...] = ()
    payloads: tuple[dict[str, Any], ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()
    status: RunStatus = RunStatus.SUCCESS


@dataclass(frozen=True)
class DurableExecutionResult:
    run_id: str
    status: RunStatus
    pipeline_type: str
    reused: bool
    supersedes_run_id: str | None
    chunk_count: int
    payload_count: int
    warning_count: int
    error_count: int


class PerFileExecutionService:
    """Own claim, lane dispatch, payload-first persistence, and durable result."""

    def __init__(
        self,
        *,
        repository: Any,
        coordinator: Any,
        dispatch: Callable[[SourceFile, bytes, str, dict[str, Any]], LaneResult],
        operator_version: str,
        chunk_schema_version: str = CHUNK_SCHEMA_VERSION,
    ) -> None:
        self.repository = repository
        self.coordinator = coordinator
        self.dispatch = dispatch
        self.operator_version = operator_version
        self.chunk_schema_version = chunk_schema_version

    def execute(
        self,
        source: SourceFile,
        source_bytes: bytes,
        config: dict[str, Any],
        *,
        overwrite: bool = False,
        orchestration_claim_key: str | None = None,
        on_run_claimed: Callable[[str], None] | None = None,
    ) -> DurableExecutionResult:
        identity = build_processing_identity(
            source,
            hashlib.sha256(source_bytes).hexdigest(),
            {"processing_config_hash": content_config_hash(config)},
            operator_version=self.operator_version,
            chunk_schema_version=self.chunk_schema_version,
        )
        claim_options: dict[str, Any] = {"overwrite": overwrite}
        if orchestration_claim_key is not None:
            claim_options["orchestration_claim_key"] = orchestration_claim_key
        claimed = self.repository.claim(source, identity, **claim_options)
        if isinstance(claimed, RunResult):
            if claimed.status is RunStatus.ACTIVE:
                raise ValueError("ACTIVE RunResult cannot be returned as a terminal result")
            if on_run_claimed is not None:
                on_run_claimed(claimed.run_id)
            return self._result(claimed, pipeline_type=source.mime_family)
        if on_run_claimed is not None:
            on_run_claimed(claimed)

        try:
            lane = self.dispatch(source, source_bytes, claimed, config)
            persisted = self.coordinator.persist(
                claimed,
                list(lane.chunks),
                list(_configured_payload_entries(lane.payloads, config)),
                logical_file_key=logical_file_key(source),
                diagnostics=list(lane.diagnostics),
                status=lane.status,
            )
        except (ConnectionError, OSError, TimeoutError):
            raise
        except Exception:
            failure = Diagnostic(
                "error",
                "deterministic_processing_failure",
                "deterministic_processing_failure",
                "per_file_execution",
            )
            self.coordinator.persist(
                claimed,
                [],
                [],
                logical_file_key=logical_file_key(source),
                diagnostics=[failure],
                status=RunStatus.FAILED,
            )
            raise
        return self._result(persisted, pipeline_type=lane.pipeline_type)

    @staticmethod
    def _result(result: RunResult, *, pipeline_type: str) -> DurableExecutionResult:
        return DurableExecutionResult(
            run_id=result.run_id,
            status=result.status,
            pipeline_type=pipeline_type,
            reused=result.reused,
            supersedes_run_id=result.supersedes_run_id,
            chunk_count=result.chunk_count,
            payload_count=result.payload_count,
            warning_count=result.warning_count,
            error_count=result.error_count,
        )


def build_v12_dispatcher() -> Callable[[SourceFile, bytes, str, dict[str, Any]], LaneResult]:
    """Return the one validated, Airflow-independent v1.2 lane dispatcher.

    Builders remain the owners of parsing/chunking.  This function only proves
    the bounded source format and selects their established lane contract.
    """

    def dispatch(
        source: SourceFile, content: bytes, run_id: str, config: dict[str, Any]
    ) -> LaneResult:
        warnings = _format_warnings(source, content)
        actual = _actual_format(content)
        if actual == "invalid":
            raise ValueError("corrupt or invalid source format")
        if actual == "unsupported":
            return LaneResult(
                pipeline_type="unsupported",
                diagnostics=tuple(warnings + [_diagnostic("unsupported_format", "warning")]),
                status=RunStatus.SKIPPED,
            )

        suffix = source.extension
        with tempfile.TemporaryDirectory(prefix="lore-v12-lane-") as directory:
            path = Path(directory) / f"source{suffix or _suffix_for(actual)}"
            path.write_bytes(content)
            if _is_transcript(source):
                return _run_transcript(source, content, run_id, config, warnings)
            if suffix in {".md", ".markdown"}:
                from lore_splitter.documents.chunking import build_document_chunks

                result = build_document_chunks(
                    run_id=run_id,
                    file_id=source.file_id,
                    markdown=content.decode("utf-8"),
                    pipeline_type="markdown",
                    source_file=source,
                    image_bucket=str(config.get("image_toast_bucket", "")),
                )
                return _lane_result("markdown", result, warnings, config)
            if suffix in {".xlsx", ".xlsm"}:
                from lore_splitter.resolver import ResolvedFile
                from lore_splitter.xlsx.chunking import build_workbook_chunks
                from lore_splitter.xlsx.workbook import extract_workbooks

                extracted = extract_workbooks((ResolvedFile(source, path),))
                if not extracted.workbooks:
                    raise ValueError("corrupt workbook")
                result = build_workbook_chunks(
                    run_id=run_id, file_id=source.file_id, workbook=extracted.workbooks[0]
                )
                return _lane_result("workbook", result, warnings, config)
            if suffix == ".pptx":
                from lore_splitter.documents.presentations import (
                    build_presentation_chunks,
                )

                result = build_presentation_chunks(
                    run_id=run_id, file_id=source.file_id, presentation=path
                )
                return _lane_result("presentation", result, warnings, config)
            if suffix == ".pdf":
                from lore_splitter.documents.pdfs import build_pdf_chunks

                result = build_pdf_chunks(run_id=run_id, file_id=source.file_id, pdf=path)
                if result.classification.kind == "scanned_or_unsupported":
                    return LaneResult(
                        "pdf_scanned_or_unsupported",
                        diagnostics=_diagnostics(result.diagnostics, warnings),
                        status=RunStatus.SKIPPED,
                    )
                pipeline_type = (
                    "pdf_presentation"
                    if result.classification.kind == "presentation_like"
                    else "pdf_document"
                )
                return _lane_result(pipeline_type, result, warnings, config)
            if suffix == ".docx":
                from lore_splitter.documents.chunking import build_document_chunks
                from lore_splitter.documents.contracts import (
                    DocumentInputArtifact,
                )
                from lore_splitter.documents.conversion import (
                    DocumentMarkdownConverter,
                )

                document = DocumentInputArtifact(
                    **{
                        **source.to_dict(),
                        "local_path": str(path),
                        "input_kind": "document",
                        "normalized_extension": suffix,
                        "mime_family": "word-processing",
                    }
                )
                converted = DocumentMarkdownConverter().convert(document)
                result = build_document_chunks(
                    run_id=run_id,
                    file_id=source.file_id,
                    markdown=converted.markdown,
                    pipeline_type="document",
                    source_file=source,
                    document_checksum=converted.document_checksum,
                    image_bucket=str(config.get("image_toast_bucket", "")),
                )
                return _lane_result("document", result, warnings, config)
        return LaneResult(
            "unsupported",
            diagnostics=tuple(warnings + [_diagnostic("unsupported_format", "warning")]),
            status=RunStatus.SKIPPED,
        )

    return dispatch


def _actual_format(content: bytes) -> str:
    if content.startswith(b"%PDF-"):
        return "pdf"
    if content.startswith(b"PK\x03\x04"):
        return "zip-container"
    if not content:
        return "invalid"
    if b"\x00" in content[:4096]:
        return "unsupported"
    return "text"


def _suffix_for(actual: str) -> str:
    return ".pdf" if actual == "pdf" else ".bin"


def _format_warnings(source: SourceFile, content: bytes) -> list[Diagnostic]:
    actual = _actual_format(content)
    expected = {
        ".pdf": "pdf",
        ".xlsx": "zip-container",
        ".xlsm": "zip-container",
        ".docx": "zip-container",
        ".pptx": "zip-container",
    }.get(source.extension)
    if expected and expected != actual:
        return [_diagnostic("format_mime_disagreement", "warning")]
    return []


def _diagnostic(code: str, level: str) -> Diagnostic:
    return Diagnostic(level, code, code, "format_validation")


def _diagnostics(values: Any, warnings: list[Diagnostic]) -> tuple[Diagnostic, ...]:
    converted = list(warnings)
    for value in values:
        if isinstance(value, Diagnostic):
            converted.append(value)
        elif isinstance(value, dict):
            code = str(value.get("code", "lane_warning"))
            converted.append(Diagnostic("warning", code, code, "lane", value))
    return tuple(converted)


def _payload_entries(
    plans: tuple[Any, ...], config: dict[str, Any] | None = None
) -> tuple[dict[str, Any], ...]:
    """Convert completed lane storage plans to coordinator-owned payload entries."""
    entries: list[dict[str, Any]] = []
    occurrence_ordinals: dict[str, int] = {}
    for original_plan in plans:
        plan = _configured_image_destination(original_plan, config or {})
        is_table = hasattr(plan, "table_name")
        payload_id = str(getattr(plan, "toast_id"))
        if is_table:
            content_hash = getattr(plan, "content_signature", None)
            if (
                not isinstance(content_hash, str)
                or len(content_hash) != 64
                or any(character not in "0123456789abcdef" for character in content_hash)
            ):
                raise ValueError("table content_signature must be 64 lowercase hex characters")
        else:
            content_hash = getattr(plan, "checksum_sha256", "")
        occurrence_ordinal = occurrence_ordinals.get(payload_id, 0)
        occurrence_ordinals[payload_id] = occurrence_ordinal + 1
        entries.append(
            {
                "payload_id": payload_id,
                "kind": "table" if is_table else "image",
                "plan": plan,
                "storage_identity": payload_id,
                "content_hash": str(content_hash),
                "occurrence_ordinal": occurrence_ordinal,
                "coordinates": dict(getattr(plan, "source_location", {}) or {}),
                "metadata": {},
            }
        )
    return tuple(entries)


def _lane_result(
    pipeline_type: str,
    result: Any,
    warnings: list[Diagnostic],
    config: dict[str, Any],
) -> LaneResult:
    return LaneResult(
        pipeline_type,
        tuple(result.chunks),
        _payload_entries(tuple(getattr(result, "payload_plans", ())), config),
        _diagnostics(result.diagnostics, warnings),
    )


def _is_transcript(source: SourceFile) -> bool:
    kind = str(source.metadata.get("pipeline_type", "")).lower()
    return source.extension in {".srt", ".vtt"} or kind == "meeting_transcript"


def _run_transcript(
    source: SourceFile,
    content: bytes,
    run_id: str,
    config: dict[str, Any],
    warnings: list[Diagnostic],
) -> LaneResult:
    """Adapt the completed all-or-nothing lane without allowing it to own core persistence."""
    from lore_splitter.transcripts.lane import run_transcript_lane

    class CaptureCoordinator:
        def __init__(self) -> None:
            self.chunks: tuple[Chunk, ...] = ()
            self.diagnostics: tuple[Diagnostic, ...] = ()
            self.status = RunStatus.FAILED

        def persist(self, _run_id, chunks, _payloads, *, diagnostics, status):
            self.chunks = tuple(chunks)
            self.diagnostics = tuple(diagnostics)
            self.status = status
            return None

    client = config.get("transcript_client")
    tokenizer = config.get("transcript_tokenizer")
    if client is None or tokenizer is None:
        raise ValueError("transcript model adapter is unavailable")
    capture = CaptureCoordinator()
    run_transcript_lane(
        run_id,
        source.file_id,
        content.decode("utf-8"),
        client=client,
        tokenizer=tokenizer,
        coordinator=capture,
    )
    return LaneResult(
        "meeting_transcript",
        capture.chunks if capture.status is RunStatus.SUCCESS else (),
        (),
        tuple(warnings) + tuple(capture.diagnostics),
        capture.status,
    )


def _configured_image_destination(plan: Any, config: dict[str, Any]) -> Any:
    if not hasattr(plan, "object_key"):
        return plan
    bucket = str(config.get("image_toast_bucket") or plan.bucket)
    prefix = str(config.get("image_toast_prefix") or "").strip("/")
    key = str(plan.object_key).lstrip("/")
    return replace(plan, bucket=bucket, object_key=f"{prefix}/{key}" if prefix else key)


def _configured_payload_entries(
    payloads: tuple[dict[str, Any], ...], config: dict[str, Any]
) -> tuple[dict[str, Any], ...]:
    """Apply the resolved image destination at the service persistence boundary."""
    configured: list[dict[str, Any]] = []
    for payload in payloads:
        if payload.get("kind") != "image":
            configured.append(payload)
            continue
        configured.append(
            {**payload, "plan": _configured_image_destination(payload["plan"], config)}
        )
    return tuple(configured)
