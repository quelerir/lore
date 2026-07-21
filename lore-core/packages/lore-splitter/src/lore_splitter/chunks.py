"""Airflow-independent retrieval chunk contracts and deterministic builders."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

from lore_core_domain.text import normalize_text

CHUNK_SCHEMA_VERSION = "chunk/v1"
_REF_RE = re.compile(r"\[payload:([A-Za-z0-9_.:-]+):([A-Za-z]+):(\d+)\]")


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()




@dataclass(frozen=True)
class ChunkCoordinates:
    heading_path: tuple[str, ...] = ()
    page: int | None = None
    slide: int | None = None
    page_start: int | None = None
    page_end: int | None = None
    slide_start: int | None = None
    slide_end: int | None = None
    internal_boundaries: tuple[str, ...] = ()
    sheet: str | None = None
    cell_range: str | None = None
    speaker: str | None = None
    speakers: tuple[str, ...] = ()
    start_ms: int | None = None
    end_ms: int | None = None
    slot_boundaries: tuple[str, ...] = ()
    continuation_lineage: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in {
                "heading_path": list(self.heading_path),
                "page": self.page,
                "slide": self.slide,
                "page_start": self.page_start,
                "page_end": self.page_end,
                "slide_start": self.slide_start,
                "slide_end": self.slide_end,
                "internal_boundaries": list(self.internal_boundaries),
                "sheet": self.sheet,
                "range": self.cell_range,
                "speaker": self.speaker,
                "speakers": list(self.speakers),
                "start_ms": self.start_ms,
                "end_ms": self.end_ms,
                "slot_boundaries": list(self.slot_boundaries),
                "continuation_lineage": list(self.continuation_lineage),
            }.items()
            if value is not None and value != []
        }


@dataclass(frozen=True)
class PayloadRef:
    payload_id: str
    kind: str
    occurrence_ordinal: int

    def __post_init__(self) -> None:
        if not self.payload_id or not self.kind or self.occurrence_ordinal < 0:
            raise ValueError("invalid_payload_ref")

    def to_dict(self) -> dict[str, Any]:
        return {
            "payload_id": self.payload_id,
            "kind": self.kind,
            "occurrence_ordinal": self.occurrence_ordinal,
        }

    def compact(self) -> str:
        return f"[payload:{self.payload_id}:{self.kind}:{self.occurrence_ordinal}]"


@dataclass(frozen=True)
class ChunkBudget:
    max_display_chars: int = 12000
    max_vector_chars: int = 8000
    max_fulltext_chars: int = 16000


@dataclass(frozen=True)
class VectorBudget:
    target_tokens: int = 768
    hard_limit_tokens: int = 1024

    def __post_init__(self) -> None:
        if self.target_tokens < 1 or self.target_tokens > self.hard_limit_tokens:
            raise ValueError("invalid_vector_budget")


def validate_vector_text(text: str, *, tokenizer: Any, budget: VectorBudget | None = None) -> str:
    active = budget or VectorBudget()
    if not isinstance(text, str) or not text.strip():
        raise ChunkValidationError("empty_vector_text")
    normalized = normalize_text(text)
    tokens = tokenizer.count(normalized)
    if tokens > active.hard_limit_tokens:
        raise ChunkValidationError("vector_token_hard_limit")
    return normalized


class ChunkValidationError(ValueError):
    """Stable, safe validation failure identified by ``code``."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message or code)


@dataclass(frozen=True)
class Chunk:
    run_id: str
    file_id: str
    ordinal: int
    pipeline_type: str
    chunk_type: str
    display_text: str
    vector_text: str
    fulltext: str
    coordinates: ChunkCoordinates = field(default_factory=ChunkCoordinates)
    payload_refs: tuple[PayloadRef, ...] = ()
    schema_version: str = CHUNK_SCHEMA_VERSION
    chunk_id: str = ""
    content_signature: str = ""
    vector_hash: str = ""
    fulltext_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "file_id": self.file_id,
            "ordinal": self.ordinal,
            "pipeline_type": self.pipeline_type,
            "chunk_type": self.chunk_type,
            "display_text": self.display_text,
            "vector_text": self.vector_text,
            "fulltext": self.fulltext,
            "coordinates": self.coordinates.to_dict(),
            "payload_refs": [ref.to_dict() for ref in self.payload_refs],
            "schema_version": self.schema_version,
            "chunk_id": self.chunk_id,
            "content_signature": self.content_signature,
            "vector_hash": self.vector_hash,
            "fulltext_hash": self.fulltext_hash,
        }


def _semantic(chunk: dict[str, Any]) -> dict[str, Any]:
    return {
        key: chunk[key]
        for key in (
            "schema_version",
            "pipeline_type",
            "chunk_type",
            "display_text",
            "vector_text",
            "fulltext",
            "coordinates",
            "payload_refs",
        )
    }


def _make_chunk(**values: Any) -> Chunk:
    values["display_text"] = normalize_text(values["display_text"])
    values["vector_text"] = normalize_text(values["vector_text"])
    values["fulltext"] = normalize_text(values["fulltext"])
    base = Chunk(**values)
    data = base.to_dict()
    return Chunk(
        **{
            **values,
            "chunk_id": _sha([base.run_id, base.ordinal, base.schema_version])[:32],
            "content_signature": _sha(_semantic(data)),
            "vector_hash": hashlib.sha256(base.vector_text.encode()).hexdigest(),
            "fulltext_hash": hashlib.sha256(base.fulltext.encode()).hexdigest(),
        }
    )


def validate_chunk(
    chunk: Chunk, *, ordinal: int | None = None, budget: ChunkBudget | None = None
) -> None:
    if (ordinal if ordinal is not None else chunk.ordinal) < 0:
        raise ChunkValidationError("invalid_ordinal")
    budget = budget or ChunkBudget()
    for name, text, limit in (
        ("display_text", chunk.display_text, budget.max_display_chars),
        ("vector_text", chunk.vector_text, budget.max_vector_chars),
        ("fulltext", chunk.fulltext, budget.max_fulltext_chars),
    ):
        if not text.strip():
            raise ChunkValidationError(f"empty_{name}")
        if len(text) > limit:
            raise ChunkValidationError(f"budget_{name}")
    if chunk.payload_refs and any(
        ref.compact() not in chunk.display_text for ref in chunk.payload_refs
    ):
        raise ChunkValidationError("unresolved_payload_ref")
    if chunk.display_text.lstrip().startswith("#") and not chunk.vector_text.lstrip().startswith(
        "#"
    ):
        raise ChunkValidationError("stranded_heading")


def _split_body(body: str, limit: int) -> list[str]:
    if len(body) <= limit:
        return [body]
    paragraphs = [part for part in body.split("\n\n") if part]
    pieces: list[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = paragraph if not current else current + "\n\n" + paragraph
        if current and len(candidate) > limit:
            pieces.append(current)
            current = paragraph
        else:
            current = candidate
    if current:
        pieces.append(current)
    result: list[str] = []
    for piece in pieces:
        if len(piece) <= limit:
            result.append(piece)
            continue
        sentences = re.split(r"(?<=[.!?])\s+", piece)
        current = ""
        for sentence in sentences:
            if current and len(current) + 1 + len(sentence) > limit:
                result.append(current)
                current = sentence
            else:
                current = sentence if not current else current + " " + sentence
        if current:
            result.append(current)
    return result


def build_chunk(
    *,
    run_id: str,
    file_id: str,
    ordinal: int,
    pipeline_type: str,
    chunk_type: str,
    display_text: str,
    vector_text: str,
    fulltext: str,
    coordinates: ChunkCoordinates | None = None,
    payload_refs: tuple[PayloadRef, ...] = (),
    schema_version: str = CHUNK_SCHEMA_VERSION,
    budget: ChunkBudget | None = None,
) -> Chunk | list[Chunk]:
    budget = budget or ChunkBudget()
    coordinates = coordinates or ChunkCoordinates()
    display = normalize_text(display_text)
    vector = normalize_text(vector_text)
    full = normalize_text(fulltext)
    heading = "\n\n".join(
        f"{'#' * min(index + 1, 6)} {item}" for index, item in enumerate(coordinates.heading_path)
    )
    if len(vector) <= budget.max_vector_chars and len(full) <= budget.max_fulltext_chars:
        chunk = _make_chunk(
            run_id=run_id,
            file_id=file_id,
            ordinal=ordinal,
            pipeline_type=pipeline_type,
            chunk_type=chunk_type,
            display_text=display,
            vector_text=vector,
            fulltext=full,
            coordinates=coordinates,
            payload_refs=payload_refs,
            schema_version=schema_version,
        )
        validate_chunk(chunk, budget=budget)
        return chunk
    body_vector = (
        vector[len(heading) :].lstrip("\n") if heading and vector.startswith(heading) else vector
    )
    body_full = full[len(heading) :].lstrip("\n") if heading and full.startswith(heading) else full
    pieces = _split_body(body_full, max(1, budget.max_fulltext_chars - len(heading) - 2))
    vector_pieces = _split_body(body_vector, max(1, budget.max_vector_chars - len(heading) - 2))
    chunks = []
    for index, piece in enumerate(pieces):
        piece_vector = vector_pieces[index] if index < len(vector_pieces) else piece
        prefix = heading + "\n\n" if heading else ""
        chunks.append(
            _make_chunk(
                run_id=run_id,
                file_id=file_id,
                ordinal=ordinal + index,
                pipeline_type=pipeline_type,
                chunk_type=chunk_type,
                display_text=display if index == 0 else piece,
                vector_text=prefix + piece_vector,
                fulltext=prefix + piece,
                coordinates=coordinates,
                payload_refs=payload_refs if index == 0 else (),
                schema_version=schema_version,
            )
        )
    for chunk in chunks:
        validate_chunk(chunk, budget=budget)
    return chunks
