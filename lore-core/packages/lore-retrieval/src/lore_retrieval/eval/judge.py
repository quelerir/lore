"""Judge-based answer-quality scaffold for the eval harness.

Retrieval/citation metrics (``harness.py``) are deterministic offline; answer
QUALITY (faithfulness, does-it-address-the-question) needs a model to read the
answer against its evidence. This module is that seam:

* ``JudgeVerdict`` / ``Judge`` — the typed contract.
* ``parse_judge_response`` — pure parser of the judge model's JSON (offline-tested).
* ``LlmJudge`` — wraps ANY ``ChatModel`` (e.g. the same OpenRouter model) as a judge;
  its parsing is offline-testable with a scripted ``FakeChatModel``.
* ``FakeJudge`` — deterministic stand-in for harness plumbing tests.

Live use: pass a real ``LlmJudge`` to ``run_eval`` to score answers, then A/B a
prompt/knob change by comparing ``judge_score`` across runs. The judgment itself
needs a live model; everything here is exercised offline.
"""
import json
import re
from dataclasses import dataclass
from typing import Protocol

from lore_retrieval.interfaces import ChatModel

_JSON = re.compile(r"\{.*\}", re.DOTALL)


@dataclass(frozen=True)
class JudgeVerdict:
    faithful: bool      # answer supported by the evidence (no invented facts)
    addressed: bool     # answer actually responds to the question
    score: float        # overall quality in [0, 1]
    reason: str


class Judge(Protocol):
    async def judge(
        self, question: str, answer: str, evidence: list[str]
    ) -> JudgeVerdict: ...


def parse_judge_response(text: str) -> JudgeVerdict:
    """Extract the judge's JSON verdict from its (possibly prose-wrapped) output.
    Coerces/clamps fields; an unparseable response is a safe zero verdict rather
    than an exception (a broken judge must not sink the eval run)."""
    match = _JSON.search(text or "")
    if match is None:
        return JudgeVerdict(False, False, 0.0, "unparseable")
    try:
        data = json.loads(match.group(0))
    except (ValueError, TypeError):
        return JudgeVerdict(False, False, 0.0, "unparseable")
    try:
        score = float(data.get("score", 0.0))
    except (ValueError, TypeError):
        score = 0.0
    score = max(0.0, min(1.0, score))
    return JudgeVerdict(
        faithful=bool(data.get("faithful", False)),
        addressed=bool(data.get("addressed", False)),
        score=score,
        reason=str(data.get("reason", "")),
    )


def build_judge_prompt(question: str, answer: str, evidence: list[str]) -> str:
    ev = "\n".join(f"- {text}" for text in evidence) or "(нет свидетельств)"
    return "\n".join(
        [
            "Ты — строгий оценщик ответов ассистента базы знаний. Оцени ответ ТОЛЬКО "
            "относительно свидетельств: опирается ли он на них и отвечает ли на вопрос.",
            "",
            f"Вопрос: {question}",
            "Свидетельства:",
            ev,
            f"Ответ: {answer}",
            "",
            'Верни ТОЛЬКО JSON: {"faithful": true|false, "addressed": true|false, '
            '"score": число 0..1, "reason": "кратко"}',
            "- faithful: ответ не содержит фактов вне свидетельств.",
            "- addressed: ответ отвечает на вопрос (или корректно сообщает, что данных нет).",
            "- score: общая оценка качества.",
        ]
    )


class LlmJudge:
    """A ``Judge`` backed by any ``ChatModel`` (reuse the answer model as judge)."""

    def __init__(self, chat_model: ChatModel) -> None:
        self._model = chat_model

    async def judge(
        self, question: str, answer: str, evidence: list[str]
    ) -> JudgeVerdict:
        text = await self._model.generate(build_judge_prompt(question, answer, evidence))
        return parse_judge_response(text)


class FakeJudge:
    """Deterministic stand-in: addressed iff there is an answer; faithful iff the
    answer shares a token with the evidence. Enough to test harness plumbing."""

    async def judge(
        self, question: str, answer: str, evidence: list[str]
    ) -> JudgeVerdict:
        answered = bool((answer or "").strip())
        answer_tokens = set(re.findall(r"\w+", (answer or "").lower()))
        evidence_tokens = set(re.findall(r"\w+", " ".join(evidence).lower()))
        faithful = answered and bool(answer_tokens & evidence_tokens)
        score = 1.0 if faithful else (0.5 if answered else 0.0)
        return JudgeVerdict(faithful=faithful, addressed=answered, score=score, reason="fake")


def aggregate_judge(verdicts: list[JudgeVerdict]) -> dict:
    n = len(verdicts)
    if n == 0:
        return {"judge_n": 0, "judge_faithful": 0.0, "judge_addressed": 0.0, "judge_score": 0.0}
    return {
        "judge_n": n,
        "judge_faithful": sum(1 for v in verdicts if v.faithful) / n,
        "judge_addressed": sum(1 for v in verdicts if v.addressed) / n,
        "judge_score": sum(v.score for v in verdicts) / n,
    }
