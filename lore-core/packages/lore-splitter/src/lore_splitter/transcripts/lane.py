"""Pure all-or-nothing transcript processing orchestration."""
# ruff: noqa: E501

from __future__ import annotations

from lore_splitter.chunks import ChunkBudget, VectorBudget
from lore_splitter.per_file import Diagnostic, RunStatus

from lore_splitter.transcripts.batching import BatchBudget, plan_batch, transition_after_response
from lore_splitter.transcripts.contracts import LaneResult, ParserDiagnosticCode
from lore_splitter.transcripts.llm import BatchLLMConfig, run_batch
from lore_splitter.transcripts.parser import parse_transcript
from lore_splitter.transcripts.rendering import render_group
from lore_splitter.transcripts.validation import validate_envelope


def _diagnostic(code: str, level: str = "error", stage: str = "transcript", details=None) -> Diagnostic:
    return Diagnostic(level, code, code, stage, details or {})


def _finish(coordinator, run_id, status, diagnostics):
    result = coordinator.persist(run_id, [], [], diagnostics=diagnostics, status=status)
    return LaneResult(status.value, (), tuple(diagnostics), result if isinstance(result, dict) else None)


def run_transcript_lane(
    run_id: str,
    file_id: str,
    source_text: str,
    *,
    client,
    tokenizer,
    coordinator,
    batch_budget: BatchBudget | None = None,
    llm_config: BatchLLMConfig | None = None,
    chunk_budget: ChunkBudget | None = None,
    vector_budget: VectorBudget | None = None,
) -> LaneResult:
    parsed = parse_transcript(source_text)
    if not parsed.slots:
        diagnostic = _diagnostic(ParserDiagnosticCode.NO_RELIABLE_SLOTS.value, "warning", "parser")
        return _finish(coordinator, run_id, RunStatus.SKIPPED, [diagnostic])

    active_budget = batch_budget or BatchBudget()
    remaining = parsed.slots
    finalized = []
    ordinal = 0
    try:
        while remaining:
            request = plan_batch(remaining, tokenizer=tokenizer, budget=active_budget, ordinal=ordinal)
            outcome = run_batch(client, request, config=llm_config, validate=lambda value, req: validate_envelope(value, req, tokenizer=tokenizer))
            if not outcome.ok:
                failure = outcome.failure
                return _finish(coordinator, run_id, RunStatus.FAILED, [_diagnostic(failure.error_code, details={"batch": failure.batch_ordinal})])
            transition = transition_after_response(request, tuple(group.slot_ids for group in outcome.envelope.groups), tokenizer=tokenizer)
            finalized_ids = set(transition.finalized_slot_ids)
            source_tail = remaining[len(request.slots):]
            if not source_tail:
                finalized.extend(outcome.envelope.groups)
                remaining = ()
            else:
                finalized.extend(group for group in outcome.envelope.groups if set(group.slot_ids).issubset(finalized_ids))
                remaining = transition.carried_slots + source_tail
            if not remaining:
                break
            ordinal += 1
        slots_by_id = {slot.slot_id: slot for slot in parsed.slots}
        chunks = []
        for index, group in enumerate(finalized):
            chunks.extend(render_group(run_id, file_id, index, group, slots_by_id, chunk_budget=chunk_budget, vector_budget=vector_budget, tokenizer=tokenizer))
        if not chunks:
            return _finish(coordinator, run_id, RunStatus.FAILED, [_diagnostic("LLM-COVERAGE")])
        coordinator.persist(run_id, chunks, [], diagnostics=[], status=RunStatus.SUCCESS)
        return LaneResult("success", tuple(chunks), ())
    except Exception as exc:
        code = getattr(exc, "code", "TRAN-04-VALIDATION")
        return _finish(coordinator, run_id, RunStatus.FAILED, [_diagnostic(str(code))])


process_transcript = run_transcript_lane
