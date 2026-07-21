"""Row-to-DTO mapping and semantic preflight computation for the audit read repository."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from lore_audit.read_contracts import (
    ChunkPreview,
    DiagnosticDetail,
    FileCard,
    PayloadOccurrenceDetail,
    ReadRunDetail,
    RunComparison,
    SemanticPreflightCounts,
)
from lore_audit.read_cursor import CursorCodec, TextWindowBuilder
from lore_audit.run_status import RunStatus
from lore_audit.read_contracts import AuditReadError, ChunkDetail, ChunkDetailRequest


def map_file(row: Any) -> FileCard:
    if len(row) != 5:
        raise ValueError
    return FileCard(row[0], row[1], RunStatus(row[2]), row[3], row[4])


def map_run(row: Any, *, expected_run_id: str | None = None) -> ReadRunDetail:
    if len(row) != 11 or (expected_run_id is not None and row[0] != expected_run_id):
        raise ValueError
    return ReadRunDetail(
        run_id=row[0],
        logical_file_key=row[1],
        status=RunStatus(row[2]),
        source_content_hash=row[3],
        config_hash=row[4],
        claimed_at=row[5],
        finished_at=row[6],
        chunk_count=row[7],
        payload_count=row[8],
        warning_count=row[9],
        error_count=row[10],
    )


def map_preview(row: Any) -> ChunkPreview:
    if len(row) != 6:
        raise ValueError
    return ChunkPreview(
        chunk_id=row[0],
        run_id=row[1],
        ordinal=row[2],
        pipeline_type=row[3],
        chunk_type=row[4],
        content_signature=row[5],
    )


def map_detail(
    row: Any,
    request: ChunkDetailRequest,
    text_windows: TextWindowBuilder,
) -> ChunkDetail:
    if len(row) != 13:
        raise ValueError
    preview = ChunkPreview(
        chunk_id=row[0],
        run_id=row[1],
        ordinal=row[2],
        pipeline_type=row[3],
        chunk_type=row[4],
        content_signature=row[10],
    )
    display_hash = hashlib.sha256(row[7].encode("utf-8")).hexdigest()
    return ChunkDetail(
        preview=preview,
        display_text=text_windows.window(
            row[7],
            run_id=row[1],
            chunk_id=row[0],
            field="display_text",
            content_hash=display_hash,
            max_bytes=request.bounds.max_text_bytes,
            continuation=request.display_continuation,
        ),
        full_text=text_windows.window(
            row[6],
            run_id=row[1],
            chunk_id=row[0],
            field="full_text",
            content_hash=row[12],
            max_bytes=request.bounds.max_text_bytes,
            continuation=request.full_continuation,
        ),
        vector_text=text_windows.window(
            row[5],
            run_id=row[1],
            chunk_id=row[0],
            field="vector_text",
            content_hash=row[11],
            max_bytes=request.bounds.max_text_bytes,
            continuation=request.vector_continuation,
        ),
        coordinates=row[8],
        payload_refs=tuple(row[9]),
    )


def map_occurrence(row: Any) -> PayloadOccurrenceDetail:
    if len(row) != 6:
        raise ValueError
    return PayloadOccurrenceDetail(
        run_id=row[0],
        payload_id=row[1],
        occurrence_ordinal=row[2],
        kind=row[3],
        chunk_id=row[4],
        coordinates=row[5],
    )


def map_diagnostic(row: Any) -> DiagnosticDetail:
    if len(row) != 8:
        raise ValueError
    return DiagnosticDetail(
        diagnostic_id=row[0],
        run_id=row[1],
        origin=row[2],
        code=row[3],
        level=row[4],
        diagnostic_key=row[5],
        chunk_id=row[6],
        payload_id=row[7],
    )


def compare_chunk_rows(
    left_id: str,
    right_id: str,
    logical_file_key: str,
    rows: tuple[Any, ...],
) -> RunComparison:
    if any(len(row) != 6 or row[0] not in {left_id, right_id} for row in rows):
        raise ValueError
    left = [row for row in rows if row[0] == left_id]
    right = [row for row in rows if row[0] == right_id]
    unchanged: list[str] = []

    def group_by_signature(values: list[Any]) -> dict[str, list[Any]]:
        groups: dict[str, list[Any]] = {}
        for row in values:
            groups.setdefault(row[3], []).append(row)
        for group in groups.values():
            group.sort(key=lambda item: (item[2], item[1]))
        return groups

    left_signatures = group_by_signature(left)
    right_signatures = group_by_signature(right)
    left_remaining: list[Any] = []
    right_remaining: list[Any] = []
    for signature in sorted(set(left_signatures) | set(right_signatures)):
        left_group = left_signatures.get(signature, [])
        right_group = right_signatures.get(signature, [])
        common = min(len(left_group), len(right_group))
        unchanged.extend(row[1] for row in left_group[:common])
        left_remaining.extend(left_group[common:])
        right_remaining.extend(right_group[common:])

    def structural_key(row: Any) -> tuple[str, str]:
        return (
            row[4],
            json.dumps(row[5], ensure_ascii=True, sort_keys=True, separators=(",", ":")),
        )

    def group_structurally(values: list[Any]) -> dict[tuple[str, str], list[Any]]:
        groups: dict[tuple[str, str], list[Any]] = {}
        for row in values:
            groups.setdefault(structural_key(row), []).append(row)
        for group in groups.values():
            group.sort(key=lambda item: (item[2], item[1]))
        return groups

    left_structural = group_structurally(left_remaining)
    right_structural = group_structurally(right_remaining)
    changed: list[tuple[str, str]] = []
    removed: list[str] = []
    added: list[str] = []
    for key in sorted(set(left_structural) | set(right_structural)):
        left_group = left_structural.get(key, [])
        right_group = right_structural.get(key, [])
        common = min(len(left_group), len(right_group))
        changed.extend(
            (left_group[index][1], right_group[index][1]) for index in range(common)
        )
        removed.extend(row[1] for row in left_group[common:])
        added.extend(row[1] for row in right_group[common:])
    return RunComparison(
        left_id,
        right_id,
        logical_file_key,
        tuple(unchanged),
        tuple(changed),
        tuple(added),
        tuple(removed),
    )


def empty_semantic_preflight() -> SemanticPreflightCounts:
    return SemanticPreflightCounts.from_dict({
        "targets": {key: 0 for key in SemanticPreflightCounts.target_fields},
        "diagnostics": {key: 0 for key in SemanticPreflightCounts.diagnostic_fields},
        "mandatory": {key: 0 for key in SemanticPreflightCounts.mandatory_fields},
    })


def build_semantic_preflight(
    chunks: tuple[Any, ...],
    payloads: tuple[Any, ...],
    diagnostics: tuple[Any, ...],
) -> SemanticPreflightCounts:
    if (
        any(len(row) != 7 for row in chunks)
        or any(len(row) != 3 for row in payloads)
        or any(len(row) != 6 for row in diagnostics)
    ):
        raise ValueError("invalid semantic preflight row")
    chunk_rows = sorted(chunks, key=lambda row: (row[1], row[0]))
    payload_ids = {row[0] for row in payloads}
    payload_kinds = {(row[0], row[1]): str(row[2]) for row in payloads}
    table_ids = {row[0] for row in payloads if str(row[2]).casefold() == "table"}
    image_ids = {row[0] for row in payloads if str(row[2]).casefold() == "image"}
    transcript_rows = [
        row
        for row in chunk_rows
        if "transcript" in str(row[2]).casefold()
        or "transcript" in str(row[3]).casefold()
    ]
    boundaries = sum(
        left[1] + 1 == right[1] and left[2] == right[2]
        for left, right in zip(chunk_rows, chunk_rows[1:])
    )
    groups = {
        (
            str(row[0]),
            str(row[2] or row[3]),
            str(row[4] or ""),
            str(row[5] or ""),
        )
        for row in diagnostics
    }
    diagnostic_targets = {
        (
            f"chunk:{row[4]}"
            if row[4]
            else f"payload:{row[5]}"
            if row[5]
            else f"diagnostic:{row[0]}:{row[2] or row[3]}"
        )
        for row in diagnostics
    }

    edge_ids = set()
    if chunk_rows:
        edge_ids = {chunk_rows[0][0], chunk_rows[-1][0]}
    sizes = [
        (row[6], row[0])
        for row in chunk_rows
        if type(row[6]) is int and row[6] >= 0
    ]
    size_ids = {min(sizes)[1], max(sizes)[1]} if sizes else set()
    type_ids: dict[tuple[str, str], str] = {}
    for row in chunk_rows:
        type_ids.setdefault((str(row[2]), str(row[3])), row[0])
    payload_type_ids: dict[str, str] = {}
    for payload_id, _, kind in payloads:
        payload_type_ids.setdefault(str(kind), payload_id)
    referenced: set[str] = set()
    for row in chunk_rows:
        raw_refs = row[5]
        if not isinstance(raw_refs, list):
            raise ValueError("invalid persisted payload refs")
        for item in raw_refs:
            if not isinstance(item, dict) or set(item) != {
                "payload_id", "kind", "occurrence_ordinal"
            }:
                raise ValueError("invalid persisted payload ref")
            payload_id = item["payload_id"]
            kind = item["kind"]
            ordinal = item["occurrence_ordinal"]
            if (
                not isinstance(payload_id, str)
                or not payload_id
                or not isinstance(kind, str)
                or not kind
                or type(ordinal) is not int
                or ordinal < 0
            ):
                raise ValueError("invalid persisted payload ref")
            registered_kind = payload_kinds.get((payload_id, ordinal))
            if registered_kind is not None and registered_kind != kind:
                raise ValueError("persisted payload ref kind mismatch")
            referenced.add(payload_id)
    broken = referenced - payload_ids

    speakers: set[str] = set()
    time_regions: set[tuple[int, int]] = set()
    transcript_chunk_ids: set[str] = set()
    for row in transcript_rows:
        coordinates = row[4]
        if not isinstance(coordinates, dict):
            continue
        raw_speakers = coordinates.get("speakers")
        if isinstance(raw_speakers, list):
            normalized = {
                item.strip().casefold() for item in raw_speakers
                if isinstance(item, str) and item.strip()
            }
            if normalized:
                speakers.update(normalized)
                transcript_chunk_ids.add(row[0])
        slots = coordinates.get("slot_boundaries")
        start, end = coordinates.get("start_ms"), coordinates.get("end_ms")
        if (
            isinstance(slots, list) and slots
            and all(
                isinstance(item, str)
                and bool(item.strip())
                and len(item.encode("utf-8")) <= 512
                for item in slots
            )
            and type(start) is int and type(end) is int and 0 <= start <= end
        ):
            time_regions.add((start, end))
            transcript_chunk_ids.add(row[0])

    mandatory = (
        diagnostic_targets
        | {
            f"chunk:{item}"
            for item in edge_ids
            | size_ids
            | set(type_ids.values())
            | transcript_chunk_ids
        }
        | {f"payload:{item}" for item in set(payload_type_ids.values()) | broken}
    )
    table_targets = {f"payload:{item}" for item in table_ids} & mandatory
    targets = {
        "chunks": len(chunk_rows),
        "boundaries": boundaries,
        "source_comparisons": 1,
        "tables": len(table_ids),
        "images": len(image_ids),
        "transcript_blocks": len(transcript_rows),
        "linked_diagnostic_groups": len(groups),
        "final_synthesis": 1,
    }
    diagnostic_counts = {
        "processing": sum(row[0] != "audit_rule" for row in diagnostics),
        "audit_rule": sum(row[0] == "audit_rule" for row in diagnostics),
        "critical": sum(str(row[1]).casefold() == "critical" for row in diagnostics),
        "warning": sum(str(row[1]).casefold() == "warning" for row in diagnostics),
    }
    mandatory_counts = {
        "deduplicated_targets": len(mandatory),
        "semantic_actions": len(mandatory) + len(table_targets),
        "diagnostic_linked_targets": len(diagnostic_targets),
        "edge_chunks": len(edge_ids),
        "size_extremes": len(size_ids),
        "chunk_types": len(type_ids),
        "payload_types": len(payload_type_ids),
        "broken_references": len(broken),
        "transcript_speakers": len(speakers),
        "transcript_time_regions": len(time_regions),
    }
    return SemanticPreflightCounts.from_dict(
        {
            "targets": targets,
            "diagnostics": diagnostic_counts,
            "mandatory": mandatory_counts,
        }
    )


__all__ = [
    "build_semantic_preflight",
    "compare_chunk_rows",
    "empty_semantic_preflight",
    "map_detail",
    "map_diagnostic",
    "map_file",
    "map_occurrence",
    "map_preview",
    "map_run",
]
