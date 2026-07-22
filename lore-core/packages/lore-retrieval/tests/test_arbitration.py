from lore_retrieval.contracts import ContextGroup, SQLResult, SQLStatus
from lore_retrieval.fakes import FakeChatModel
from lore_retrieval.pipeline.arbitration import arbitrate_and_answer


def group(section_id, text, chunk_ids):
    return ContextGroup(
        document_id="d", section_id=section_id, section_path=("Root",), scope="window",
        chunk_ids=chunk_ids, start_position=0, end_position=len(chunk_ids),
        text=text, group_score=1.0, citations=chunk_ids,
    )


async def test_text_only_answer_uses_groups_and_no_sql():
    model = FakeChatModel(lambda p: "текстовый ответ")
    g = group("sec1", "премия считается так", ["c1", "c2"])
    d = await arbitrate_and_answer(model, "как премия?", [g], [])
    assert d.answer == "текстовый ответ"
    assert d.used_evidence_chunk_ids == ["c1", "c2"]
    assert d.used_sql_payload_ids == []
    assert "премия считается так" in model.calls[0]   # evidence reached the prompt


async def test_single_sql_success_is_used():
    model = FakeChatModel()
    ok = SQLResult(payload_id="pay1", chunk_id="t1", status=SQLStatus.success, answer_summary="42")
    d = await arbitrate_and_answer(model, "сколько?", [], [ok])
    assert d.used_sql_payload_ids == ["pay1"]
    assert d.note is None


async def test_conflicting_sql_successes_stay_explicit():
    model = FakeChatModel()
    a = SQLResult(payload_id="pay1", chunk_id="t1", status=SQLStatus.success, answer_summary="42")
    b = SQLResult(payload_id="pay2", chunk_id="t2", status=SQLStatus.success, answer_summary="99")
    d = await arbitrate_and_answer(model, "сколько?", [], [a, b])
    assert d.note == "conflicting_sql_results"
    assert set(d.used_sql_payload_ids) == {"pay1", "pay2"}   # both kept, not merged
    assert "расходятся" in model.calls[0]


async def test_no_evidence_returns_limitation_without_calling_model():
    model = FakeChatModel()
    failed = [
        SQLResult(payload_id="pay1", chunk_id="t1", status=SQLStatus.empty),
        SQLResult(payload_id="pay2", chunk_id="t2", status=SQLStatus.not_applicable),
    ]
    d = await arbitrate_and_answer(model, "сколько?", [], failed)
    assert d.note == "no_grounded_evidence"
    assert d.answer == ""
    assert model.calls == []                                 # no invented facts


async def test_sql_successes_continue_the_marker_sequence():
    model = FakeChatModel(lambda p: "ответ [1] [2]")
    g = group("sec1", "текст группы", ["c1"])               # text -> [1]
    ok = SQLResult(payload_id="p1", chunk_id="a1", status=SQLStatus.success, answer_summary="итог")
    d = await arbitrate_and_answer(model, "вопрос", [g], [ok])   # SQL success -> [2]
    assert d.evidence_map == {1: ["c1"]}
    assert d.sql_evidence_map == {2: "a1"}
    assert "[2] payload p1" in model.calls[0]


async def test_sql_only_grounding_still_prompts_for_markers():
    model = FakeChatModel(lambda p: "ответ [1]")
    ok = SQLResult(payload_id="p1", chunk_id="a1", status=SQLStatus.success, answer_summary="s")
    d = await arbitrate_and_answer(model, "вопрос", [], [ok])
    assert d.sql_evidence_map == {1: "a1"}
    assert "[1] payload p1" in model.calls[0]
    assert "маркер" in model.calls[0].lower()
