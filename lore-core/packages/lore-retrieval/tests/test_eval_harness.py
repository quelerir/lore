"""Offline eval harness (P5 first slice): metrics are pure; the runner drives the
in-memory pipeline over a small RU fixture. No live backends."""
from lore_retrieval.contracts import Citation, ContextGroup, PipelineResult, TableCandidate
from lore_retrieval.eval.cases import GOLDEN_CASES
from lore_retrieval.eval.harness import (
    CaseMetrics,
    aggregate,
    evaluate_case,
    format_report,
    run_eval,
)


def _group(chunk_id):
    return ContextGroup(
        document_id="d", section_id="s", section_path=("H",), scope="window",
        chunk_ids=[chunk_id], start_position=0, end_position=1, text="t",
        group_score=1.0, citations=[chunk_id],
    )


def _cite(chunk_id, marker, kind="text"):
    return Citation(
        chunk_id=chunk_id, run_id="r", logical_file_key="f", preview_text="p",
        heading_path=(), deep_link="/files?...", kind=kind, marker=marker,
    )


def _result(groups=(), citations=(), table_candidates=()):
    return PipelineResult(
        decision={"answer": "a", "used_evidence_chunk_ids": [], "used_sql_payload_ids": [],
                  "citations": []},
        groups=list(groups),
        sql_results=[],
        table_candidates=list(table_candidates),
        citations=list(citations),
        rejected_evidence=[],
        degradations=[],
    )


def _metrics(**over):
    base = dict(
        has_gold=True, retrieval_hit=True, citation_hit=True, grounded=True,
        fell_back=False, answered=True, answer_expected=True,
    )
    base.update(over)
    return CaseMetrics(**base)


def test_evaluate_case_marks_hits_grounding_and_fallback():
    result = _result(groups=[_group("c1")], citations=[_cite("c1", 1)])
    m = evaluate_case(result, gold_chunk_ids=("c1",))
    assert m == _metrics()   # positive, cited, grounded, answered, no fallback


def test_evaluate_case_detects_fallback_and_grounding_violation():
    # Fallback: a citation with marker=None. Grounding violation: cited chunk not retrieved.
    result = _result(groups=[_group("c1")], citations=[_cite("cX", None)])
    m = evaluate_case(result, gold_chunk_ids=("c1",))
    assert m.citation_hit is False          # gold c1 not cited (cited cX)
    assert m.grounded is False              # cX not in retrieved evidence
    assert m.fell_back is True              # marker=None


def test_evaluate_case_table_candidate_counts_as_retrieved():
    result = _result(
        table_candidates=[TableCandidate(chunk_id="t1", payload_id="p1", score=1.0, run_id="r")],
        citations=[_cite("t1", 1, kind="table")],
    )
    m = evaluate_case(result, gold_chunk_ids=("t1",))
    assert m.retrieval_hit and m.citation_hit and m.grounded


def test_evaluate_case_decline_expected_and_answered():
    # A negative case (no gold) that correctly declines: answer empty, expect_answer=False.
    result = _result()   # decision.answer is non-empty ("a") in the helper
    m = evaluate_case(result, gold_chunk_ids=(), expect_answer=False)
    assert m.has_gold is False
    assert m.answered is True                # helper answer "a"
    assert m.answer_expected is False        # answered != expected -> decline miss


def test_aggregate_splits_recall_over_gold_cases_only():
    metrics = [
        _metrics(),                                          # positive, cited
        _metrics(citation_hit=False, fell_back=True),        # positive, fell back
        _metrics(has_gold=False, retrieval_hit=False, citation_hit=False,
                 answered=False, answer_expected=False),     # negative, declined correctly
    ]
    report = aggregate(metrics)
    assert report["n"] == 3 and report["n_gold"] == 2
    assert report["retrieval_recall"] == 1.0                 # over the 2 gold cases
    assert report["citation_recall"] == 0.5
    assert report["grounding"] == 1.0
    assert report["fallback_rate"] == 1 / 3
    assert report["answer_rate"] == 2 / 3
    assert report["decline_correct"] == 1.0                  # all answered==expected


def test_aggregate_empty_is_safe():
    report = aggregate([])
    assert report["n"] == 0 and report["n_gold"] == 0 and report["citation_recall"] == 0.0


async def test_run_eval_over_the_golden_fixture():
    report = await run_eval(GOLDEN_CASES)
    assert report["n"] == len(GOLDEN_CASES) >= 3
    # Positive cases always retrieve their gold and grounding holds everywhere.
    assert report["retrieval_recall"] == 1.0
    assert report["grounding"] == 1.0
    # At least one case cites its gold, one falls back, and the decline case declines.
    assert report["citation_recall"] > 0.0
    assert report["fallback_rate"] > 0.0
    assert report["decline_correct"] == 1.0   # every case answered iff it should
    assert "decline_correct" in format_report(report)
