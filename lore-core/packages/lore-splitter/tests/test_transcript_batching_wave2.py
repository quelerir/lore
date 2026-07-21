from lore_splitter.transcripts.batching import (
    BatchBudget,
    BatchRequest,
    plan_batch,
)
from lore_splitter.transcripts.contracts import TranscriptSlot


class FixedTokenizer:
    def count(self, text: str) -> int:
        return len(text.split())


def slots(*texts: str) -> tuple[TranscriptSlot, ...]:
    return tuple(TranscriptSlot(f"s{index:04d}", index - 1, "Speaker", index, None, text)
                 for index, text in enumerate(texts, 1))


def test_batch_planner_reserves_output_and_renders_complete_raw_slots():
    budget = BatchBudget(input_tokens=34, output_tokens=4, prompt_tokens=2, tail_tokens=5)
    request = plan_batch(
        slots("one two", "three four", "five six"), tokenizer=FixedTokenizer(), budget=budget
    )

    assert isinstance(request, BatchRequest)
    assert [slot.slot_id for slot in request.slots] == ["s0001", "s0002"]
    assert request.input_tokens <= 34
    assert request.reserved_output_tokens == 4
    assert "cleaned" not in request.rendered_request


def test_batch_planner_keeps_request_and_retrieval_budgets_separate():
    budget = BatchBudget(input_tokens=30, output_tokens=4, prompt_tokens=1, tail_tokens=3,
                         vector_target_tokens=768, vector_hard_limit_tokens=1024)
    request = plan_batch(slots("one two"), tokenizer=FixedTokenizer(), budget=budget)

    assert request.budget.vector_target_tokens == 768
    assert request.budget.vector_hard_limit_tokens == 1024
    assert request.budget.input_tokens == 30
