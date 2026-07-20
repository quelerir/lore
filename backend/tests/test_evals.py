"""Юниты eval-харнесса: без сети и без LangSmith, только фейки."""

import json
from pathlib import Path

import pytest
from langchain_openai import ChatOpenAI

import config
from evals.dataset import EvalCase, load_cases, to_examples
from evals.models import build_eval_model

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
