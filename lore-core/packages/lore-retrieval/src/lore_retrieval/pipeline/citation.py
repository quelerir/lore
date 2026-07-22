"""Citation stage — resolve the model's [n] markers into FileViewer references.

The model places ``[n]`` markers referencing the evidence enumeration it was
shown (text ``evidence_map`` + ``sql_evidence_map``). This pure step maps used
markers to ``Citation``s built from the already-verified ``EvidenceEnvelope``s
(text, ``tab=display``) and the SQL successes (table, ``tab=payloads``), and
builds the FileViewer deep-link. Markers that don't match provided evidence are
ignored (no invented sources). When the model resolves no marker but grounding
existed, a deterministic top-N fallback cites the shown evidence in order.
"""
import re
from urllib.parse import quote

from lore_retrieval.contracts import (
    Citation,
    EvidenceEnvelope,
    SQLResult,
    TableCandidate,
)

_MARKER = re.compile(r"\[(\d+)\]")


def build_deep_link(
    logical_file_key: str, run_id: str, chunk_id: str, *, tab: str = "display"
) -> str:
    return (
        f"/files?file={quote(logical_file_key, safe='')}"
        f"&run={quote(run_id, safe='')}"
        f"&chunk={quote(chunk_id, safe='')}&tab={quote(tab, safe='')}"
    )


def _text_citation(
    chunk_id: str,
    envelope: EvidenceEnvelope,
    file_key_by_run: dict[str, str],
    preview_chars: int,
    marker: int | None,
) -> Citation:
    # Fall back to run_id as the file key when the run->file mapping is unknown
    # (still yields a viewer link; membership re-validated there).
    file_key = file_key_by_run.get(envelope.run_id, envelope.run_id)
    heading = tuple(envelope.coordinates.get("heading_path") or ())
    preview = (envelope.display_text or envelope.fulltext)[:preview_chars]
    return Citation(
        chunk_id=chunk_id,
        run_id=envelope.run_id,
        logical_file_key=file_key,
        preview_text=preview,
        heading_path=heading,
        deep_link=build_deep_link(file_key, envelope.run_id, chunk_id, tab="display"),
        kind="text",
        marker=marker,
    )


def _table_citation(
    chunk_id: str,
    sql_result: SQLResult,
    candidate: TableCandidate,
    file_key_by_run: dict[str, str],
    preview_chars: int,
    marker: int | None,
) -> Citation | None:
    run_id = candidate.run_id
    if not run_id:  # no provenance -> cannot build a valid deep-link; skip
        return None
    file_key = file_key_by_run.get(run_id, run_id)
    preview = (sql_result.answer_summary or "")[:preview_chars]
    return Citation(
        chunk_id=chunk_id,
        run_id=run_id,
        logical_file_key=file_key,
        preview_text=preview,
        heading_path=candidate.heading_path,
        deep_link=build_deep_link(file_key, run_id, chunk_id, tab="payloads"),
        kind="table",
        marker=marker,
    )


def build_citations(
    answer: str,
    evidence_map: dict[int, list[str]],
    envelope_by_chunk: dict[str, EvidenceEnvelope],
    file_key_by_run: dict[str, str],
    *,
    sql_evidence_map: dict[int, str] | None = None,
    sql_result_by_chunk: dict[str, SQLResult] | None = None,
    table_candidate_by_chunk: dict[str, TableCandidate] | None = None,
    preview_chars: int = 160,
    limit: int = 8,
    fallback_limit: int = 3,
) -> list[Citation]:
    sql_evidence_map = sql_evidence_map or {}
    sql_result_by_chunk = sql_result_by_chunk or {}
    table_candidate_by_chunk = table_candidate_by_chunk or {}

    citations: list[Citation] = []
    seen_chunks: set[str] = set()
    seen_payloads: set[str] = set()

    def add_text(chunk_id: str, marker: int | None) -> None:
        if chunk_id in seen_chunks or len(citations) >= limit:
            return
        envelope = envelope_by_chunk.get(chunk_id)
        if envelope is None:
            return
        seen_chunks.add(chunk_id)
        citations.append(
            _text_citation(chunk_id, envelope, file_key_by_run, preview_chars, marker)
        )

    def add_table(anchor: str, marker: int | None) -> None:
        if len(citations) >= limit:
            return
        sql_result = sql_result_by_chunk.get(anchor)
        candidate = table_candidate_by_chunk.get(anchor)
        if sql_result is None or candidate is None:
            return
        if candidate.payload_id in seen_payloads:
            return
        cit = _table_citation(
            anchor, sql_result, candidate, file_key_by_run, preview_chars, marker
        )
        if cit is None:
            return
        seen_payloads.add(candidate.payload_id)
        citations.append(cit)

    # 1) Resolve model markers in order of first appearance.
    ordered: list[int] = []
    seen_idx: set[int] = set()
    for m in _MARKER.finditer(answer):
        idx = int(m.group(1))
        if idx not in seen_idx:
            seen_idx.add(idx)
            ordered.append(idx)
    for idx in ordered:
        if idx in evidence_map:
            for chunk_id in evidence_map[idx]:
                add_text(chunk_id, idx)
        elif idx in sql_evidence_map:
            add_table(sql_evidence_map[idx], idx)

    if citations:
        return citations

    # 2) Deterministic fallback: no resolvable markers but grounding existed ->
    #    top-N in shown order (text groups first, then SQL successes), marker=None.
    if not evidence_map and not sql_evidence_map:
        return []
    for idx in sorted(set(evidence_map) | set(sql_evidence_map)):
        if len(citations) >= fallback_limit:
            break
        if idx in evidence_map:
            for chunk_id in evidence_map[idx]:
                add_text(chunk_id, None)
        else:
            add_table(sql_evidence_map[idx], None)
    return citations
