"""Citation stage — resolve the model's [n] markers into FileViewer references.

The model places ``[n]`` markers referencing the evidence enumeration it was
shown (``AgentDecision.evidence_map``). This pure step maps used markers to
``Citation``s built from the already-verified ``EvidenceEnvelope``s, and builds
the FileViewer deep-link. Markers that don't match provided evidence are ignored
(no invented sources).
"""
import re
from urllib.parse import quote

from lore_retrieval.contracts import Citation, EvidenceEnvelope

_MARKER = re.compile(r"\[(\d+)\]")


def build_deep_link(logical_file_key: str, run_id: str, chunk_id: str) -> str:
    return (
        f"/files?file={quote(logical_file_key, safe='')}"
        f"&run={quote(run_id, safe='')}"
        f"&chunk={quote(chunk_id, safe='')}&tab=display"
    )


def build_citations(
    answer: str,
    evidence_map: dict[int, list[str]],
    envelope_by_chunk: dict[str, EvidenceEnvelope],
    file_key_by_run: dict[str, str],
    *,
    preview_chars: int = 160,
    limit: int = 8,
) -> list[Citation]:
    # Marker indices in order of first appearance.
    ordered: list[int] = []
    seen_idx: set[int] = set()
    for m in _MARKER.finditer(answer):
        idx = int(m.group(1))
        if idx not in seen_idx:
            seen_idx.add(idx)
            ordered.append(idx)

    citations: list[Citation] = []
    seen_chunks: set[str] = set()
    for idx in ordered:
        for chunk_id in evidence_map.get(idx, []):  # non-provided index -> ignored
            if chunk_id in seen_chunks:
                continue
            envelope = envelope_by_chunk.get(chunk_id)
            if envelope is None:
                continue
            seen_chunks.add(chunk_id)
            # Fall back to run_id as the file key when the run->file mapping is
            # unknown (still yields a viewer link; membership re-validated there).
            file_key = file_key_by_run.get(envelope.run_id, envelope.run_id)
            heading = tuple(envelope.coordinates.get("heading_path") or ())
            preview = (envelope.display_text or envelope.fulltext)[:preview_chars]
            citations.append(
                Citation(
                    chunk_id=chunk_id,
                    run_id=envelope.run_id,
                    logical_file_key=file_key,
                    preview_text=preview,
                    heading_path=heading,
                    deep_link=build_deep_link(file_key, envelope.run_id, chunk_id),
                )
            )
            if len(citations) >= limit:
                return citations
    return citations
