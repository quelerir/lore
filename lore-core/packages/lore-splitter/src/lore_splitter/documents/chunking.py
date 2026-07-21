"""Structural Markdown-to-retrieval-chunk composition for document lanes."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lore_splitter.chunks import (
    Chunk,
    ChunkBudget,
    ChunkCoordinates,
    PayloadRef,
    build_chunk,
)
from lore_splitter.contracts import SourceFile
from lore_splitter.documents.external_images import (
    Fetcher,
    fetch_external_image,
)
from lore_splitter.documents.images import (
    build_image_storage_plans,
    classify_image_candidate,
)
from lore_splitter.markdown.contracts import MarkdownTableLocation, TableData
from lore_splitter.markdown.profile import profile_table
from lore_splitter.markdown.toast import classify_table
from lore_splitter.storage import build_table_storage_plan

_HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)\s*$")


@dataclass(frozen=True)
class DocumentBlock:
    kind: str
    text: str
    heading_path: tuple[str, ...]
    line_start: int
    line_end: int


@dataclass(frozen=True)
class DocumentChunkResult:
    chunks: tuple[Chunk, ...]
    payload_plans: tuple[Any, ...] = ()
    diagnostics: tuple[dict[str, Any], ...] = ()


def parse_markdown_blocks(markdown: str) -> tuple[DocumentBlock, ...]:
    """Parse Markdown into ordered blocks while retaining heading hierarchy."""
    lines = markdown.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    blocks: list[DocumentBlock] = []
    heading_stack: list[str] = []
    pending: list[str] = []
    start = 1
    fenced = False

    def flush(end: int) -> None:
        nonlocal pending, start
        text = "\n".join(pending).strip("\n")
        if text.strip():
            kind = "code" if fenced else _block_kind(text)
            blocks.append(DocumentBlock(kind, text, tuple(heading_stack), start, end))
        pending = []

    for number, line in enumerate(lines, 1):
        heading = None if fenced else _HEADING.match(line)
        if heading:
            flush(number - 1)
            level = len(heading.group(1))
            heading_stack[:] = heading_stack[: level - 1]
            heading_stack.append(heading.group(2).strip())
            blocks.append(
                DocumentBlock("heading", line.strip(), tuple(heading_stack), number, number)
            )
            start = number + 1
            continue
        if line.strip().startswith("```"):
            if not pending:
                start = number
            pending.append(line)
            fenced = not fenced
            if not fenced:
                flush(number)
            continue
        if not line.strip():
            flush(number - 1)
            start = number + 1
            continue
        if not pending:
            start = number
        pending.append(line)
    flush(len(lines))
    return tuple(blocks)


def build_document_chunks(
    *,
    run_id: str,
    file_id: str,
    markdown: str,
    pipeline_type: str = "document",
    budget: ChunkBudget | None = None,
    source_file: SourceFile | None = None,
    document_checksum: str | None = None,
    image_fetch_enabled: bool = False,
    image_fetcher: Fetcher | None = None,
    image_bucket: str = "lore-payloads",
    image_max_bytes: int = 5 * 1024 * 1024,
) -> DocumentChunkResult:
    resolved_document_checksum = document_checksum or hashlib.sha256(
        markdown.encode("utf-8")
    ).hexdigest()
    chunks: list[Chunk] = []
    payload_plans: list[Any] = []
    diagnostics: list[dict[str, Any]] = []
    occurrences: dict[tuple[str, str], int] = {}
    ordinal = 0
    for block in parse_markdown_blocks(markdown):
        coordinates = ChunkCoordinates(heading_path=block.heading_path)
        display = block.text
        refs: list[PayloadRef] = []
        if block.kind == "table_candidate":
            table = _table_data(
                block,
                file_id=file_id,
                source_file=source_file,
                document_checksum=resolved_document_checksum,
            )
            if table is not None:
                decision = classify_table(table, profile_table(table))
                if decision.classification == "toast" and decision.toast_id:
                    plan = build_table_storage_plan(table, profile_table(table), decision)
                    ref = _payload_ref(
                        decision.toast_id, "table", occurrences, plan.source_location or {}
                    )
                    payload_plans.append(plan)
                    refs.append(ref)
                    display = decision.toast_id and ref.compact()
                    payload_text = _payload_context(
                        block.heading_path,
                        f"table columns: {', '.join(table.columns)}; "
                        f"rows: {len(table.rows) - 1}; "
                        f"location: lines {block.line_start}-{block.line_end}\n{ref.compact()}",
                    )
                    payload_chunk = build_chunk(
                        run_id=run_id,
                        file_id=file_id,
                        ordinal=ordinal,
                        pipeline_type=pipeline_type,
                        chunk_type="table_payload",
                        display_text=payload_text,
                        vector_text=payload_text,
                        fulltext=payload_text,
                        coordinates=coordinates,
                        payload_refs=(ref,),
                        budget=budget,
                    )
                    payload_chunks = (
                        payload_chunk if isinstance(payload_chunk, list) else [payload_chunk]
                    )
                    chunks.extend(payload_chunks)
                    ordinal += len(payload_chunks)
        display, image_refs = _image_references(
            display,
            run_id=run_id,
            file_id=file_id,
            enabled=image_fetch_enabled,
            fetcher=image_fetcher,
            max_bytes=image_max_bytes,
            bucket=image_bucket,
            payload_plans=payload_plans,
            occurrences=occurrences,
            diagnostics=diagnostics,
        )
        refs.extend(image_refs)
        context = _heading_text(block.heading_path)
        retrieval = display if block.kind == "heading" else _join_context(context, display)
        built = build_chunk(
            run_id=run_id,
            file_id=file_id,
            ordinal=ordinal,
            pipeline_type=pipeline_type,
            chunk_type="heading" if block.kind == "heading" else "text",
            display_text=display,
            vector_text=retrieval,
            fulltext=retrieval,
            coordinates=coordinates,
            payload_refs=tuple(refs),
            budget=budget,
        )
        built_chunks = built if isinstance(built, list) else [built]
        chunks.extend(built_chunks)
        ordinal += len(built_chunks)
    return DocumentChunkResult(
        chunks=tuple(chunks), payload_plans=tuple(payload_plans), diagnostics=tuple(diagnostics)
    )


def _heading_text(path: tuple[str, ...]) -> str:
    return "\n\n".join(f"{'#' * min(index + 1, 6)} {title}" for index, title in enumerate(path))


def _join_context(context: str, text: str) -> str:
    return f"{context}\n\n{text}" if context else text


def _block_kind(text: str) -> str:
    stripped = text.lstrip()
    if stripped.startswith(("- ", "* ", "+ ")) or re.match(r"\d+[.)] ", stripped):
        return "list"
    if stripped.startswith(">"):
        return "blockquote"
    if stripped.startswith("<table") and stripped.endswith("</table>"):
        return "html_table"
    if "|" in text and "\n" in text:
        return "table_candidate"
    return "paragraph"


_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+[^)]*)?\)")


def _table_data(
    block: DocumentBlock,
    *,
    file_id: str,
    source_file: SourceFile | None,
    document_checksum: str,
) -> TableData | None:
    lines = block.text.splitlines()
    if len(lines) < 2:
        return None
    rows = [_split_pipe(line) for line in lines]
    if len(rows[0]) < 1 or len(rows[1]) != len(rows[0]):
        return None
    if not all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in rows[1]):
        return None
    source = source_file or SourceFile(
        source_id=file_id,
        stream="document",
        file_id=file_id,
        source_path=file_id,
        object_path=file_id,
        mime_type="text/markdown",
        size_bytes=0,
    )
    return TableData(
        source_file=source,
        local_path=Path(source.object_path),
        source_kind="document",
        source_checksum=document_checksum,
        table_index=block.line_start,
        columns=tuple(rows[0]),
        rows=tuple(tuple(row) for row in [rows[0], *rows[2:]]),
        markdown=MarkdownTableLocation(block.line_start, block.line_start, block.line_end),
    )


def _split_pipe(line: str) -> list[str]:
    value = line.strip().strip("|")
    return [cell.strip() for cell in value.split("|")]


def _payload_ref(
    payload_id: str,
    kind: str,
    occurrences: dict[tuple[str, str], int],
    _location: dict[str, Any],
) -> PayloadRef:
    key = (payload_id, kind)
    ordinal = occurrences.get(key, 0)
    occurrences[key] = ordinal + 1
    return PayloadRef(payload_id=payload_id, kind=kind, occurrence_ordinal=ordinal)


def _payload_context(heading_path: tuple[str, ...], body: str) -> str:
    heading = _heading_text(heading_path)
    return f"{heading}\n\n{body}" if heading else body


def _image_references(
    text: str,
    *,
    run_id: str,
    file_id: str,
    enabled: bool,
    fetcher: Fetcher | None,
    max_bytes: int,
    bucket: str,
    payload_plans: list[Any],
    occurrences: dict[tuple[str, str], int],
    diagnostics: list[dict[str, Any]],
) -> tuple[str, list[PayloadRef]]:
    refs: list[PayloadRef] = []
    for match in tuple(_IMAGE.finditer(text)):
        url = match.group(2)
        if not enabled or fetcher is None or not url.startswith(("https://", "http://")):
            continue
        try:
            candidate = fetch_external_image(url, fetcher=fetcher, max_bytes=max_bytes)
            reason = classify_image_candidate(candidate)
            if reason is not None:
                diagnostics.append({"code": "image_skipped", "reason": reason, "file_id": file_id})
                continue
            plan = build_image_storage_plans(
                type("ImageResult", (), {"unique_candidates": (candidate,)})(), bucket=bucket
            )[0]
            payload_plans.append(plan)
            ref = _payload_ref(candidate.toast_id, "image", occurrences, {})
            refs.append(ref)
            text = text.replace(match.group(0), f"{match.group(1)} {ref.compact()}", 1)
        except Exception as exc:  # noqa: BLE001 - isolate one source image safely.
            reason = str(exc) if isinstance(exc, ValueError) else "fetcher_error"
            diagnostics.append(
                {"code": "external_image_failed", "reason": reason, "file_id": file_id}
            )
    return text, refs
