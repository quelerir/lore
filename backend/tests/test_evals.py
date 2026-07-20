"""Юниты eval-харнесса: без сети и без LangSmith, только фейки."""

import asyncio
import json
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

import config
from evals.dataset import EvalCase, ensure_dataset, load_cases, to_examples
from evals.evaluators import (
    JudgeCorrectness,
    executes_ok,
    has_rows,
    make_answer_correct,
    status_ok,
)
from evals.models import build_eval_model
from fakes import ScriptedChatModel, StructuredScriptedChatModel

_CASE = {
    "question": "Какие ФИО у юристов?",
    "chunk_id": "c1",
    "table": "toast_tbl_ec48a6d52d16ab405f95",
    "desc_vector": "юристы Adventum",
    "desc_full": "Таблица юристов: колонки column_1, senior_legal_manager",
    "reference_answer": "Суворова Юлия Александровна",
}


def _settings(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    config.get_settings.cache_clear()
    return config.get_settings()


def test_build_eval_model_openrouter(monkeypatch):
    model = build_eval_model("openai/gpt-4o", _settings(monkeypatch))
    assert isinstance(model, ChatOpenAI)
    assert model.model_name == "openai/gpt-4o"
    assert model.temperature == 0.0


def test_build_eval_model_requires_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    config.get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        build_eval_model("openai/gpt-4o", config.get_settings())


def test_load_cases_parses(tmp_path):
    p = tmp_path / "cases.json"
    p.write_text(json.dumps([_CASE], ensure_ascii=False), encoding="utf-8")
    cases = load_cases(p)
    assert len(cases) == 1
    assert isinstance(cases[0], EvalCase)
    assert cases[0].table == "toast_tbl_ec48a6d52d16ab405f95"


def test_load_cases_rejects_missing_field(tmp_path):
    bad = {k: v for k, v in _CASE.items() if k != "reference_answer"}
    p = tmp_path / "bad.json"
    p.write_text(json.dumps([bad], ensure_ascii=False), encoding="utf-8")
    with pytest.raises(Exception):
        load_cases(p)


def test_to_examples_shape():
    ex = to_examples([EvalCase(**_CASE)])
    assert ex[0]["inputs"].keys() == {
        "question", "chunk_id", "table", "desc_vector", "desc_full",
    }
    assert ex[0]["outputs"] == {"reference_answer": "Суворова Юлия Александровна"}


DATASET_PATH = (
    Path(__file__).resolve().parent.parent / "evals" / "datasets" / "sql_cases.json"
)


def test_real_dataset_loads_and_is_complete():
    cases = load_cases(DATASET_PATH)
    assert len(cases) == 5
    for c in cases:
        assert c.table.startswith("toast_tbl_")
        assert c.question.strip()
        assert c.reference_answer.strip()
        assert c.desc_full.strip()


_OK_OUT = {
    "status": "ok",
    "rows_used": 3,
    "sql_attempts": [{"sql": "SELECT 1", "ok": True, "error": None, "row_count": 3}],
}
_FAIL_OUT = {
    "status": "error",
    "rows_used": 0,
    "sql_attempts": [{"sql": "SELECT x", "ok": False, "error": "boom", "row_count": 0}],
}


def test_executes_ok():
    assert executes_ok(_OK_OUT) == {"key": "executes_ok", "score": 1}
    assert executes_ok(_FAIL_OUT) == {"key": "executes_ok", "score": 0}


def test_status_ok():
    assert status_ok(_OK_OUT)["score"] == 1
    assert status_ok(_FAIL_OUT)["score"] == 0


def test_has_rows():
    assert has_rows(_OK_OUT)["score"] == 1
    assert has_rows(_FAIL_OUT)["score"] == 0


def _judge_call(judge):
    ev = make_answer_correct(judge)
    return asyncio.run(ev(
        inputs={"question": "ФИО юристов?"},
        outputs={"answer": "Суворова Юлия Александровна"},
        reference_outputs={"reference_answer": "Суворова Юлия Александровна"},
    ))


def test_answer_correct_structured_true():
    judge = StructuredScriptedChatModel(
        responses=[JudgeCorrectness(correct=True, reason="совпало")]
    )
    res = _judge_call(judge)
    assert res["key"] == "answer_correct"
    assert res["score"] == 1
    assert res["comment"] == "совпало"


def test_answer_correct_text_fallback_false():
    # ScriptedChatModel.with_structured_output кидает NotImplementedError →
    # текстовый фолбэк; без слова "correct" вердикт отрицательный.
    judge = ScriptedChatModel(responses=[AIMessage("incorrect: не совпало")])
    res = _judge_call(judge)
    assert res["score"] == 0


class _FakeDataset:
    id = "ds-1"


class _FakeClient:
    def __init__(self, exists):
        self._exists = exists
        self.created_examples = None
        self.created_dataset = False

    def has_dataset(self, dataset_name):
        return self._exists

    def create_dataset(self, dataset_name):
        self.created_dataset = True
        return _FakeDataset()

    def create_examples(self, dataset_id, examples):
        self.created_examples = examples


def test_ensure_dataset_creates_when_absent():
    client = _FakeClient(exists=False)
    name = ensure_dataset(client, "sql-eval", [EvalCase(**_CASE)])
    assert name == "sql-eval"
    assert client.created_dataset is True
    assert len(client.created_examples) == 1


def test_ensure_dataset_skips_when_present():
    client = _FakeClient(exists=True)
    ensure_dataset(client, "sql-eval", [EvalCase(**_CASE)])
    assert client.created_dataset is False
    assert client.created_examples is None
