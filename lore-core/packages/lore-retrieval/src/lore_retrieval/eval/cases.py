"""Golden fixture for the offline eval harness — small, RU, hand-labelled.

Each case pairs a tiny corpus + query with a scripted model answer and the gold
source chunk. Grow this set as regressions surface; it's the offline safety net
before live eval. (Live cases will reuse the same ``EvalCase`` shape.)
"""
from lore_retrieval.eval.harness import EvalCase
from lore_retrieval.source import SourceChunk


def _txt(chunk_id: str, ordinal: int, path: tuple[str, ...], text: str) -> SourceChunk:
    return SourceChunk(
        chunk_id=chunk_id, document_id="d1", run_id="d1", chunk_type="text",
        position=ordinal, heading_path=path, vector_text=text, fulltext=text,
        display_text=text, vector_text_hash="h", fulltext_hash="h",
    )


_PREMIA = [
    _txt("c1", 1, ("Root", "Премия"), "премия сотрудника формула расчёта"),
    _txt("c2", 2, ("Root", "Премия"), "формула премии зависит от оклада"),
]

# Corpus with an off-topic distractor: the relevant chunk must still be retrieved
# and cited without the distractor polluting the grounding.
_MIXED = [
    _txt("v1", 1, ("Root", "Отпуск"), "отпуск оформляется заявлением за две недели"),
    _txt("v2", 2, ("Root", "Парковка"), "парковка для гостей офиса на первом этаже"),
]


GOLDEN_CASES: list[EvalCase] = [
    EvalCase(
        name="cites_gold_marker",
        query="премия сотрудника формула",
        corpus=_PREMIA,
        responder=lambda _prompt: "Премия считается по формуле [1].",
        gold_chunk_ids=("c1",),
        file_keys={"d1": "premia.pdf"},
    ),
    EvalCase(
        name="no_markers_falls_back",
        query="премия сотрудника формула",
        corpus=_PREMIA,
        responder=lambda _prompt: "Ответ без маркеров.",
        gold_chunk_ids=("c1",),
        file_keys={"d1": "premia.pdf"},
    ),
    EvalCase(
        name="distractor_does_not_pollute",
        query="как оформить отпуск заявление",
        corpus=_MIXED,
        responder=lambda _prompt: "Отпуск оформляется заявлением [1].",
        gold_chunk_ids=("v1",),
        file_keys={"d1": "office.pdf"},
    ),
    EvalCase(
        name="declines_when_no_evidence",
        query="конфигурация гиперпространственного двигателя",
        corpus=_PREMIA,
        responder=lambda _prompt: "Я не должен отвечать без источников.",
        gold_chunk_ids=(),          # negative case: nothing should ground
        file_keys={"d1": "premia.pdf"},
        expect_answer=False,        # pipeline must decline (empty answer), not invent
    ),
]
