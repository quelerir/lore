import json
# ruff: noqa: E501, I001
from dataclasses import FrozenInstanceError, is_dataclass

from lore_splitter.chunks import ChunkCoordinates
from lore_splitter.transcripts.contracts import (
    DiscardedOccurrence,
    DiscardReason,
    InternalBoundary,
    LaneResult,
    ParsedTranscript,
    ParserDiagnostic,
    ParserDiagnosticCode,
    TranscriptMetadata,
    TranscriptSlot,
)
from lore_splitter.transcripts.parser import parse_transcript


def test_llm_retry_controller_passes_timeout_and_never_switches_model():
    from lore_splitter.transcripts.batching import BatchBudget, plan_batch
    from lore_splitter.transcripts.llm import (
        BatchLLMConfig,
        RetryableLLMError,
        run_batch,
    )

    class Tokenizer:
        def count(self, text):
            return len(text.split())

    class Client:
        def __init__(self):
            self.calls = []

        def request(self, rendered_request, *, model_id, per_call_timeout_seconds):
            self.calls.append((model_id, per_call_timeout_seconds))
            if len(self.calls) < 3:
                raise RetryableLLMError("timeout")
            return {"groups": [{"slot_ids": ["s0001"], "heading": "Topic", "markdown": "Text"}]}

    slot = TranscriptSlot("s0001", 0, "Алиса", 0, None, "Текст")
    request = plan_batch(
        (slot,),
        tokenizer=Tokenizer(),
        budget=BatchBudget(input_tokens=40, output_tokens=4, prompt_tokens=1),
    )
    client = Client()
    outcome = run_batch(
        client,
        request,
        config=BatchLLMConfig(per_call_timeout_seconds=7, retry_delay_seconds=0),
        validate=lambda envelope, _: envelope,
        clock=lambda: 0,
        sleep=lambda _: None,
    )

    assert outcome.ok
    assert client.calls == [("qwen/qwen3.6-plus", 7)] * 3


def test_llm_retry_exhaustion_is_redacted_and_has_no_partial_success():
    from lore_splitter.transcripts.batching import BatchBudget, plan_batch
    from lore_splitter.transcripts.llm import (
        BatchLLMConfig,
        RetryableLLMError,
        run_batch,
    )

    class Tokenizer:
        def count(self, text):
            return len(text.split())

    class Client:
        def request(self, *args, **kwargs):
            raise RetryableLLMError("provider body with transcript secret")

    slot = TranscriptSlot("s0001", 0, "Алиса", 0, None, "secret transcript")
    request = plan_batch(
        (slot,),
        tokenizer=Tokenizer(),
        budget=BatchBudget(input_tokens=40, output_tokens=4, prompt_tokens=1),
    )
    outcome = run_batch(
        Client(),
        request,
        config=BatchLLMConfig(max_retries=2, retry_delay_seconds=0),
        validate=lambda envelope, _: envelope,
        clock=lambda: 0,
        sleep=lambda _: None,
    )

    assert not outcome.ok
    assert outcome.failure.error_code == "LLM-RETRY-EXHAUSTED"
    assert "secret" not in str(outcome.failure)
    assert outcome.envelope is None


def test_structured_response_requires_exact_ordered_coverage_and_vector_hard_limit():
    from lore_splitter.chunks import VectorBudget, validate_vector_text
    from lore_splitter.transcripts.batching import BatchBudget, plan_batch
    from lore_splitter.transcripts.validation import (
        ResponseValidationError,
        validate_envelope,
    )

    class Tokenizer:
        def count(self, text):
            return len(text.split())

    request = plan_batch(
        (TranscriptSlot("s0001", 0, "А", 0, 1, "A"), TranscriptSlot("s0002", 1, "Б", 1, 2, "B")),
        tokenizer=Tokenizer(),
        budget=BatchBudget(input_tokens=60, output_tokens=4, prompt_tokens=1),
    )
    valid = {"groups": [{"slot_ids": ["s0001", "s0002"], "heading": "Topic", "markdown": "Facts"}]}
    assert validate_envelope(valid, request, tokenizer=Tokenizer()).groups[0].slot_ids == ("s0001", "s0002")
    try:
        validate_envelope({"groups": [{"slot_ids": ["s0002"], "heading": "T", "markdown": "M"}]}, request, tokenizer=Tokenizer())
    except ResponseValidationError as error:
        assert error.code == "LLM-NONCONTIGUOUS-COVERAGE"
    else:
        raise AssertionError("coverage must be rejected")
    try:
        validate_vector_text("x " * 5, tokenizer=Tokenizer(), budget=VectorBudget(target_tokens=3, hard_limit_tokens=4))
    except ValueError as error:
        assert getattr(error, "code", "") == "vector_token_hard_limit"
    else:
        raise AssertionError("hard token limit must reject")


def test_transcript_contracts_are_frozen_and_safe_to_serialize():
    slot = TranscriptSlot("s0001", 0, "Алиса", 61_000, 62_000, "Обсуждаем ClickHouse.")
    result = ParsedTranscript(
        metadata=TranscriptMetadata("Рабочая встреча", (("summary", 2),)),
        slots=(slot,),
        diagnostics=(ParserDiagnostic(ParserDiagnosticCode.REMOVED_SECTION, 2),),
    )

    assert all(is_dataclass(item) for item in (slot, result.metadata, result))
    assert result.to_dict()["metadata"] == {
        "title": "Рабочая встреча",
        "removed_sections": {"summary": 2},
    }
    assert "Обсуждаем" in result.to_dict()["slots"][0]["source_text"]
    assert "secret" not in json.dumps(result.to_dict()).lower()
    try:
        slot.speaker = "Боб"
    except FrozenInstanceError:
        pass
    else:
        raise AssertionError("TranscriptSlot must be frozen")


def test_discard_and_boundary_serialization_never_contains_source_text():
    discarded = DiscardedOccurrence("s0002", "Боб", 63_000, None, DiscardReason.ADMINISTRATION)
    boundary = InternalBoundary("s0001", "Алиса", 61_000, 62_000, "s0000")
    result = LaneResult(
        "skipped",
        diagnostics=(ParserDiagnostic(ParserDiagnosticCode.NO_RELIABLE_SLOTS),),
    )

    assert discarded.to_dict() == {
        "slot_id": "s0002",
        "speaker": "Боб",
        "start_ms": 63_000,
        "end_ms": None,
        "reason": "administration",
    }
    assert boundary.to_dict()["continuation_of"] == "s0000"
    assert result.to_dict()["diagnostics"][0]["code"] == "TRAN-01-NO_RELIABLE_SLOTS"
    assert "secret transcript" not in json.dumps(
        {"discarded": discarded.to_dict(), "boundary": boundary.to_dict()}
    )


def test_parser_removes_mymeet_generated_sections_and_keeps_safe_title():
    result = parse_transcript(
        """**Встреча команды**

## Супер краткое содержание
- СЕКРЕТНЫЙ СГЕНЕРИРОВАННЫЙ ТЕКСТ

## Транскрипт
[00:01] Алиса: Первый пункт.
Продолжение первого пункта.
[00:02:05] Боб: Второй пункт.
"""
    )

    assert result.metadata.title == "Встреча команды"
    assert result.metadata.removed_sections == (("summary", 1),)
    assert [slot.slot_id for slot in result.slots] == ["s0001", "s0002"]
    assert result.slots[0].source_text == "Первый пункт.\nПродолжение первого пункта."
    assert result.slots[0].start_ms == 1_000
    assert result.slots[0].end_ms == 125_000
    serialized = json.dumps(result.to_dict(), ensure_ascii=False)
    assert "СЕКРЕТНЫЙ" not in serialized


def test_parser_warns_on_malformed_markers_and_skips_without_reliable_slots():
    result = parse_transcript(
        """## Транскрипт
00:99:00 Алиса: impossible
00:02 Алиса without colon
Текст без временной метки
"""
    )

    assert result.skipped is True
    assert result.slots == ()
    assert [diagnostic.code for diagnostic in result.diagnostics] == [
        ParserDiagnosticCode.INVALID_COORDINATE,
        ParserDiagnosticCode.MALFORMED_MARKER,
        ParserDiagnosticCode.NO_RELIABLE_SLOTS,
    ]


def test_parser_discards_only_obvious_administration_and_keeps_topic_setting_speech():
    result = parse_transcript(
        """## Транскрипт
00:00 Анна: Всем привет, начинаем.
00:01 Анна: Обсудим причины задержки Airbyte.
00:02 Борис: Нужно проверить очередь и логи.
"""
    )

    assert [slot.source_text for slot in result.slots] == [
        "Обсудим причины задержки Airbyte.",
        "Нужно проверить очередь и логи.",
    ]
    assert result.discarded[0].reason is DiscardReason.GREETING_OR_CLOSING


def test_shared_coordinates_preserve_existing_fields_and_transcript_lineage():
    coordinates = ChunkCoordinates(
        heading_path=("Meeting",),
        slide=3,
        sheet="Summary",
        cell_range="A1:B4",
        speakers=("Алиса", "Боб"),
        start_ms=1_000,
        end_ms=125_000,
        slot_boundaries=(
            json.dumps(
                {"slot_id": "s0001", "speaker": "Алиса", "start_ms": 1_000, "end_ms": 125_000},
                sort_keys=True,
            ),
        ),
        continuation_lineage=("s0003<-s0002",),
    )

    serialized = coordinates.to_dict()
    assert serialized["slide"] == 3
    assert serialized["sheet"] == "Summary"
    assert serialized["range"] == "A1:B4"
    assert serialized["speakers"] == ["Алиса", "Боб"]
    assert json.loads(serialized["slot_boundaries"][0])["slot_id"] == "s0001"
    assert serialized["continuation_lineage"] == ["s0003<-s0002"]


def test_shared_coordinate_lineage_survives_oversized_chunk_splitting():
    from lore_splitter.chunks import ChunkBudget, build_chunk

    coordinates = ChunkCoordinates(
        speakers=("Алиса",),
        start_ms=1_000,
        end_ms=2_000,
        slot_boundaries=(json.dumps({"slot_id": "s0001"}),),
        continuation_lineage=("s0001-part-1",),
    )
    result = build_chunk(
        run_id="run",
        file_id="meeting",
        ordinal=0,
        pipeline_type="transcript",
        chunk_type="transcript_topic",
        display_text="Speaker: " + "word. " * 80,
        vector_text="# Topic\n\n" + "word. " * 80,
        fulltext="# Topic\n\n" + "word. " * 80,
        coordinates=coordinates,
        budget=ChunkBudget(max_display_chars=500, max_vector_chars=80, max_fulltext_chars=120),
    )

    assert isinstance(result, list)
    assert result
    assert all(
        chunk.coordinates.to_dict()["slot_boundaries"] == ['{"slot_id": "s0001"}']
        for chunk in result
    )
    assert all(
        chunk.coordinates.to_dict()["continuation_lineage"] == ["s0001-part-1"] for chunk in result
    )
