"""Bounded rolling requests over parser-owned transcript slots."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from lore_splitter.transcripts.contracts import TranscriptSlot


class Tokenizer(Protocol):
    def count(self, text: str) -> int: ...


@dataclass(frozen=True)
class BatchBudget:
    input_tokens: int = 16_384
    output_tokens: int = 8_192
    tail_tokens: int = 2_048
    prompt_tokens: int = 256
    vector_target_tokens: int = 768
    vector_hard_limit_tokens: int = 1_024

    def __post_init__(self) -> None:
        if (
            min(
                self.input_tokens,
                self.output_tokens,
                self.tail_tokens,
                self.prompt_tokens,
                self.vector_target_tokens,
                self.vector_hard_limit_tokens,
            )
            < 0
            or self.input_tokens <= self.output_tokens
        ):
            raise ValueError("invalid_transcript_token_budget")
        if self.vector_target_tokens > self.vector_hard_limit_tokens:
            raise ValueError("invalid_vector_token_budget")


@dataclass(frozen=True)
class BatchRequest:
    ordinal: int
    slots: tuple[TranscriptSlot, ...]
    rendered_request: str
    input_tokens: int
    reserved_output_tokens: int
    budget: BatchBudget
    slot_start: str = ""
    slot_end: str = ""

    def __post_init__(self) -> None:
        if not self.slots or self.input_tokens > self.budget.input_tokens:
            raise ValueError("invalid_batch_request")


@dataclass(frozen=True)
class BatchTransition:
    finalized_slot_ids: tuple[str, ...]
    carried_slots: tuple[TranscriptSlot, ...]
    continuation_lineage: tuple[str, ...] = ()


def render_raw_request(slots: tuple[TranscriptSlot, ...]) -> str:
    """Render only source slots; model prose is deliberately not accepted here."""
    body = "\n".join(f"[{slot.slot_id}] {slot.source_text}" for slot in slots)
    return (
        "Return the structured segmentation envelope for these raw transcript slots. "
        "Keep slot ids exact and do not invent coordinates.\n"
        "RAW_SLOTS:\n"
        f"{body}\n"
    )


def plan_batch(
    slots: tuple[TranscriptSlot, ...],
    *,
    tokenizer: Tokenizer,
    budget: BatchBudget | None = None,
    ordinal: int = 0,
) -> BatchRequest:
    """Pack complete slots while reserving output and fixed prompt/schema overhead."""
    active = budget or BatchBudget()
    if not slots:
        raise ValueError("empty_batch_slots")
    available = active.input_tokens - active.output_tokens
    selected: list[TranscriptSlot] = []
    for slot in slots:
        candidate = tuple([*selected, slot])
        rendered = render_raw_request(candidate)
        counted = active.prompt_tokens + tokenizer.count(rendered)
        if counted > available:
            break
        selected.append(slot)
    if not selected:
        raise ValueError("slot_exceeds_batch_budget")
    rendered = render_raw_request(tuple(selected))
    input_tokens = active.prompt_tokens + tokenizer.count(rendered)
    return BatchRequest(
        ordinal=ordinal,
        slots=tuple(selected),
        rendered_request=rendered,
        input_tokens=input_tokens,
        reserved_output_tokens=active.output_tokens,
        budget=active,
        slot_start=selected[0].slot_id,
        slot_end=selected[-1].slot_id,
    )


def transition_after_response(
    request: BatchRequest,
    groups: tuple[tuple[str, ...], ...],
    *,
    tokenizer: Tokenizer,
) -> BatchTransition:
    """Carry only the final unresolved raw group, or finalize it at the tail boundary."""
    known = {slot.slot_id: slot for slot in request.slots}
    if not groups:
        raise ValueError("empty_batch_groups")
    flattened = [slot_id for group in groups for slot_id in group]
    if set(flattened) != set(known) or len(flattened) != len(set(flattened)):
        raise ValueError("invalid_batch_coverage")
    last = groups[-1]
    carried = tuple(known[slot_id] for slot_id in last)
    tail_request = render_raw_request(carried)
    tail_tokens = request.budget.prompt_tokens + tokenizer.count(tail_request)
    finalized = tuple(slot_id for group in groups[:-1] for slot_id in group)
    if tail_tokens <= request.budget.tail_tokens:
        return BatchTransition(finalized, carried)
    return BatchTransition(
        (*finalized, *last),
        (),
        tuple(f"{slot_id}:continuation:{request.ordinal}" for slot_id in last),
    )
