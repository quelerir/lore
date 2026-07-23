"""Judge-based answer-quality scaffold — offline (fake judge / scripted model)."""
from lore_retrieval.eval.judge import (
    FakeJudge,
    JudgeVerdict,
    LlmJudge,
    aggregate_judge,
    build_judge_prompt,
    parse_judge_response,
)
from lore_retrieval.eval.cases import GOLDEN_CASES
from lore_retrieval.eval.harness import run_eval
from lore_retrieval.fakes import FakeChatModel


def test_parse_judge_response_extracts_json_amid_prose():
    text = 'Оценка: {"faithful": true, "addressed": true, "score": 0.8, "reason": "ок"} — конец.'
    v = parse_judge_response(text)
    assert v == JudgeVerdict(faithful=True, addressed=True, score=0.8, reason="ок")


def test_parse_judge_response_clamps_and_defaults():
    v = parse_judge_response('{"faithful": "yes", "score": 5}')  # score out of range, no addressed
    assert v.score == 1.0                 # clamped to [0,1]
    assert v.addressed is False           # missing -> False


def test_parse_judge_response_unparseable_is_safe():
    v = parse_judge_response("no json here")
    assert v == JudgeVerdict(faithful=False, addressed=False, score=0.0, reason="unparseable")


def test_build_judge_prompt_contains_question_answer_evidence():
    p = build_judge_prompt("вопрос?", "ответ [1]", ["свидетельство один"])
    assert "вопрос?" in p and "ответ [1]" in p and "свидетельство один" in p
    assert "JSON" in p


async def test_llm_judge_parses_the_models_verdict():
    model = FakeChatModel(lambda _p: '{"faithful": true, "addressed": true, "score": 0.9, "reason": "х"}')
    v = await LlmJudge(model).judge("q", "a [1]", ["ev"])
    assert v.faithful and v.score == 0.9


def test_aggregate_judge_means():
    verdicts = [
        JudgeVerdict(faithful=True, addressed=True, score=1.0, reason=""),
        JudgeVerdict(faithful=False, addressed=True, score=0.4, reason=""),
    ]
    agg = aggregate_judge(verdicts)
    assert agg["judge_n"] == 2
    assert agg["judge_faithful"] == 0.5
    assert agg["judge_addressed"] == 1.0
    assert agg["judge_score"] == 0.7


def test_aggregate_judge_empty_is_safe():
    agg = aggregate_judge([])
    assert agg["judge_n"] == 0 and agg["judge_score"] == 0.0


async def test_run_eval_with_judge_adds_judge_metrics():
    report = await run_eval(GOLDEN_CASES, judge=FakeJudge())
    assert report["judge_n"] == len(GOLDEN_CASES)
    for key in ("judge_faithful", "judge_addressed", "judge_score"):
        assert 0.0 <= report[key] <= 1.0


async def test_run_eval_without_judge_omits_judge_metrics():
    report = await run_eval(GOLDEN_CASES)
    assert "judge_score" not in report
