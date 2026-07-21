"""Deterministic source-faithful transcript chunk rendering."""
# ruff: noqa: E501

from __future__ import annotations

from dataclasses import replace

from lore_splitter.chunks import (
    Chunk,
    ChunkBudget,
    ChunkCoordinates,
    VectorBudget,
    build_chunk,
    validate_vector_text,
)

from lore_splitter.transcripts.contracts import TranscriptSlot
from lore_splitter.transcripts.validation import ValidatedGroup


def _timecode(milliseconds: int) -> str:
    seconds = milliseconds // 1000
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def _coordinates(slots: tuple[TranscriptSlot, ...], heading: str, lineage: tuple[str, ...]) -> ChunkCoordinates:
    return ChunkCoordinates(
        heading_path=(heading,),
        speakers=tuple(dict.fromkeys(slot.speaker for slot in slots)),
        start_ms=slots[0].start_ms,
        end_ms=slots[-1].end_ms or slots[-1].start_ms,
        slot_boundaries=tuple(slot.slot_id for slot in slots),
        internal_boundaries=tuple(f"{slot.slot_id}:{slot.start_ms}:{slot.end_ms or ''}" for slot in slots),
        continuation_lineage=lineage,
    )


def render_group(
    run_id: str,
    file_id: str,
    ordinal: int,
    group: ValidatedGroup,
    slots_by_id: dict[str, TranscriptSlot],
    *,
    chunk_budget: ChunkBudget | None = None,
    vector_budget: VectorBudget | None = None,
    tokenizer=None,
) -> tuple[Chunk, ...]:
    slots = tuple(slots_by_id[slot_id] for slot_id in group.slot_ids)
    heading = group.heading.strip()
    source_lines = [f"**{slot.speaker}** [{_timecode(slot.start_ms)}] {slot.source_text}" for slot in slots]
    full_lines = [f"**{slot.speaker}** {slot.source_text}" for slot in slots]
    display = f"# {heading}\n\n" + "\n".join(source_lines)
    fulltext = f"# {heading}\n\n" + "\n".join(full_lines)
    vector = f"# {heading}\n\n{group.markdown.strip()}"
    if tokenizer is not None:
        validate_vector_text(vector, tokenizer=tokenizer, budget=vector_budget)
    built = build_chunk(
        run_id=run_id, file_id=file_id, ordinal=ordinal, pipeline_type="transcript",
        chunk_type="transcript_topic", display_text=display, vector_text=vector,
        fulltext=fulltext, coordinates=_coordinates(slots, heading, ()), budget=chunk_budget,
    )
    chunks = tuple(built if isinstance(built, list) else [built])
    if len(chunks) > 1:
        chunks = tuple(replace(chunk, coordinates=replace(chunk.coordinates, continuation_lineage=(*chunk.coordinates.continuation_lineage, f"{slots[0].slot_id}:split:{index}"))) for index, chunk in enumerate(chunks))
    return chunks
