"""Strict validation of untrusted structured transcript responses."""
# ruff: noqa: E501

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from lore_splitter.chunks import ChunkBudget, validate_vector_text

ALLOWED_DISCARD_REASONS = {
    "administration",
    "technical_failure",
    "greeting_or_closing",
    "other_non_content",
}


class ResponseValidationError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ValidatedGroup:
    slot_ids: tuple[str, ...]
    heading: str
    markdown: str


@dataclass(frozen=True)
class ValidatedEnvelope:
    groups: tuple[ValidatedGroup, ...]
    discards: tuple[tuple[str, str], ...]


def validate_envelope(
    envelope: Any, request: Any, *, tokenizer: Any, chunk_budget: ChunkBudget | None = None
) -> ValidatedEnvelope:
    if not isinstance(envelope, dict) or not isinstance(envelope.get("groups"), list):
        raise ResponseValidationError("LLM-SCHEMA")
    expected = [slot.slot_id for slot in request.slots]
    groups: list[ValidatedGroup] = []
    covered: list[str] = []
    for item in envelope["groups"]:
        if not isinstance(item, dict) or not isinstance(item.get("slot_ids"), list):
            raise ResponseValidationError("LLM-SCHEMA")
        ids = tuple(item["slot_ids"])
        heading, markdown = item.get("heading"), item.get("markdown")
        if (
            not ids
            or not isinstance(heading, str)
            or not heading.strip()
            or not isinstance(markdown, str)
            or not markdown.strip()
        ):
            raise ResponseValidationError("LLM-EMPTY-OUTPUT")
        start = len(covered)
        if list(ids) != expected[start : start + len(ids)]:
            raise ResponseValidationError("LLM-NONCONTIGUOUS-COVERAGE")
        covered.extend(ids)
        validate_vector_text(f"# {heading}\n\n{markdown}", tokenizer=tokenizer)
        groups.append(ValidatedGroup(ids, heading, markdown))
    discards: list[tuple[str, str]] = []
    for item in envelope.get("discards", []):
        if not isinstance(item, dict) or item.get("reason") not in ALLOWED_DISCARD_REASONS:
            raise ResponseValidationError("LLM-DISCARD-REASON")
        discards.append((item.get("slot_id"), item["reason"]))
    all_ids = covered + [slot_id for slot_id, _ in discards]
    if sorted(all_ids) != sorted(expected) or len(all_ids) != len(set(all_ids)):
        raise ResponseValidationError("LLM-COVERAGE")
    return ValidatedEnvelope(tuple(groups), tuple(discards))
