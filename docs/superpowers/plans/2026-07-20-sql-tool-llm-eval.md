# SQL-инструмент: eval-харнесс для сравнения LLM — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Прогонять SQL-инструмент `toast` на фиксированном датасете вопросов с разными OpenRouter-моделями и сравнивать их в self-hosted LangSmith (корректность, выполнимость SQL, латентность/токены).

**Architecture:** Отдельный CLI-скрипт на `langsmith.aevaluate()` перебирает список моделей; для каждой строит `ChatOpenAI` и оборачивает существующий `run_sql_tool` в async-target. Датасет извлечён из `problem-questions-report.html` в закоммиченный `sql_cases.json` и синкается в LangSmith. Оценщики: детерминированные эвристики + LLM-judge с фиксированной моделью-судьёй. Код `toast/` не меняется.

**Tech Stack:** Python 3.13, langsmith SDK, langchain-openai (ChatOpenAI/OpenRouter), pydantic, pytest, asyncio.

## Global Constraints

- Provider — только OpenRouter: модели строятся как `ChatOpenAI(model=<name>, base_url=settings.openrouter_base_url, api_key=settings.openrouter_api_key)`.
- Данные не покидают контур: LangSmith self-hosted через env `LANGSMITH_ENDPOINT` / `LANGSMITH_API_KEY` / `LANGSMITH_TRACING=true` (читает сам langsmith SDK).
- Не менять код в `backend/toast/` — только обёртки в `backend/evals/`.
- Тесты не ходят в сеть и не поднимают LangSmith: только фейки (`tests/fakes.py`, `tests/graph_utils.py`).
- Модель-судья фиксирована на все эксперименты (env `EVAL_JUDGE_MODEL`), судья ≠ оцениваемая модель.
- Комментарии и строки — по-русски, как в остальном бэкенде.
- Evaluator'ы langsmith биндят аргументы **по имени параметра**: допустимы имена `inputs`, `outputs`, `reference_outputs`, `run`, `example`.
- Async-target: `async def target(inputs: dict) -> dict`.
- Команды запускать из каталога `backend/` (там `pyproject.toml`, пакеты `toast`/`agents`/`evals` — top-level).

## File Structure

```
backend/evals/
  __init__.py          # пустой маркер пакета
  models.py            # build_eval_model(name, settings, temperature) -> BaseChatModel
  dataset.py           # EvalCase, load_cases(path), to_examples(cases), ensure_dataset(client, name, cases)
  evaluators.py        # executes_ok, status_ok, has_rows, judge_correctness, make_answer_correct(judge)
  run_sql_eval.py      # make_target, parse_args, main() — CLI-точка входа
  datasets/
    sql_cases.json     # ~5 кейсов из отчёта: inputs SqlToolInput + reference_answer
backend/tests/test_evals.py   # юниты: model factory, load_cases, evaluators, ensure_dataset, target
docs/evals.md          # как запускать: env, команда, чтение результатов
backend/pyproject.toml # + зависимость langsmith
backend/config.py      # + поле eval_judge_model
.env.example           # + LANGSMITH_* и EVAL_JUDGE_MODEL
```

Контракт данных (одна запись `sql_cases.json`):
```json
{
  "question": "…",
  "chunk_id": "…",
  "table": "toast_tbl_…",
  "desc_vector": "короткая строка-саммари таблицы",
  "desc_full": "назначение таблицы + перечень колонок",
  "reference_answer": "Проверенный ответ из отчёта"
}
```
Проекция в LangSmith-пример: `inputs` = первые пять полей (ровно поля `SqlToolInput`), `outputs` = `{"reference_answer": …}`.

---

### Task 1: Пакет `evals`, фабрика моделей, зависимость и конфиг судьи

**Files:**
- Create: `backend/evals/__init__.py` (пустой)
- Create: `backend/evals/models.py`
- Modify: `backend/pyproject.toml` (добавить `langsmith` в `dependencies`)
- Modify: `backend/config.py:99` (после `sql_candidates_per_round`, добавить `eval_judge_model`)
- Test: `backend/tests/test_evals.py`

**Interfaces:**
- Produces: `build_eval_model(name: str, settings, temperature: float = 0.0) -> BaseChatModel`
- Produces: `config.Settings.eval_judge_model: str`
- Consumes: `agents.base._max_tokens_kwargs`, `config.get_settings`

- [ ] **Step 1: Добавить зависимость langsmith**

В `backend/pyproject.toml`, в массив `dependencies`, добавить строку (рядом с `langchain-openai>=1.3.5`):
```toml
    "langsmith>=0.2",
```

- [ ] **Step 2: Добавить поле судьи в конфиг**

В `backend/config.py` сразу после поля `sql_candidates_per_round` (строка ~99) добавить:
```python

    # --- Eval-харнесс: фиксированная модель-судья корректности ответа ---
    eval_judge_model: str = Field(
        default="anthropic/claude-sonnet-4.6", validation_alias="EVAL_JUDGE_MODEL"
    )
```

- [ ] **Step 3: Написать падающий тест фабрики моделей**

В `backend/tests/test_evals.py`:
```python
"""Юниты eval-харнесса: без сети и без LangSmith, только фейки."""

import pytest
from langchain_openai import ChatOpenAI

import config
from evals.models import build_eval_model


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
```

- [ ] **Step 4: Запустить тест — убедиться, что падает**

Run: `cd backend && python -m pytest tests/test_evals.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'evals'`

- [ ] **Step 5: Реализовать пакет и фабрику**

Создать `backend/evals/__init__.py` (пустой файл).

Создать `backend/evals/models.py`:
```python
"""Фабрика моделей eval-харнесса: OpenRouter через ChatOpenAI.

Единственная варьируемая ось эксперимента — имя модели. Переиспользует
_max_tokens_kwargs из agents.base, чтобы поведение предела вывода совпадало
с боевыми моделями.
"""

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

from agents.base import _max_tokens_kwargs


def build_eval_model(name: str, settings, temperature: float = 0.0) -> BaseChatModel:
    """ChatOpenAI на OpenRouter по имени модели. temperature=0 — воспроизводимость."""
    if not settings.openrouter_api_key:
        raise RuntimeError("OPENROUTER_API_KEY обязателен для eval-харнесса")
    return ChatOpenAI(
        model=name,
        base_url=settings.openrouter_base_url,
        api_key=settings.openrouter_api_key,
        temperature=temperature,
        **_max_tokens_kwargs(settings.llm_max_tokens),
    )
```

- [ ] **Step 6: Запустить тест — убедиться, что проходит**

Run: `cd backend && python -m pytest tests/test_evals.py -v`
Expected: PASS (2 passed)

- [ ] **Step 7: Установить зависимость и проверить импорт**

Run: `cd backend && uv sync && python -c "import langsmith; print(langsmith.__version__)"`
Expected: печатает версию langsmith без ошибок

- [ ] **Step 8: Commit**

```bash
git add backend/evals/__init__.py backend/evals/models.py backend/pyproject.toml backend/uv.lock backend/config.py backend/tests/test_evals.py
git commit -m "feat(evals): package skeleton, OpenRouter model factory, judge config"
```

---

### Task 2: Загрузка и валидация датасета

**Files:**
- Create: `backend/evals/dataset.py`
- Test: `backend/tests/test_evals.py` (дополнить)

**Interfaces:**
- Produces: `EvalCase` (pydantic BaseModel с полями question, chunk_id, table, desc_vector, desc_full, reference_answer)
- Produces: `load_cases(path: str | Path) -> list[EvalCase]`
- Produces: `to_examples(cases: list[EvalCase]) -> list[dict]` → `[{"inputs": {...5 полей...}, "outputs": {"reference_answer": str}}]`

- [ ] **Step 1: Написать падающий тест загрузки/проекции**

Дополнить `backend/tests/test_evals.py`:
```python
import json

from evals.dataset import EvalCase, load_cases, to_examples

_CASE = {
    "question": "Какие ФИО у юристов?",
    "chunk_id": "c1",
    "table": "toast_tbl_ec48a6d52d16ab405f95",
    "desc_vector": "юристы Adventum",
    "desc_full": "Таблица юристов: колонки column_1, senior_legal_manager",
    "reference_answer": "Суворова Юлия Александровна",
}


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
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd backend && python -m pytest tests/test_evals.py -k "load_cases or to_examples" -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'evals.dataset'`

- [ ] **Step 3: Реализовать dataset.py (без ensure_dataset — он в Task 6)**

Создать `backend/evals/dataset.py`:
```python
"""Загрузка eval-датасета из JSON и проекция в примеры LangSmith.

EvalCase фиксирует контракт одной записи; inputs совпадают с полями
SqlToolInput, outputs несут эталон для оценщика корректности.
"""

import json
from pathlib import Path

from pydantic import BaseModel

_INPUT_FIELDS = ("question", "chunk_id", "table", "desc_vector", "desc_full")


class EvalCase(BaseModel):
    question: str
    chunk_id: str
    table: str
    desc_vector: str
    desc_full: str
    reference_answer: str


def load_cases(path: str | Path) -> list[EvalCase]:
    """Прочитать JSON-массив кейсов; лишние/недостающие поля → ошибка валидации."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [EvalCase(**c) for c in data]


def to_examples(cases: list[EvalCase]) -> list[dict]:
    """EvalCase → примеры LangSmith: inputs = поля SqlToolInput, outputs = эталон."""
    return [
        {
            "inputs": {f: getattr(c, f) for f in _INPUT_FIELDS},
            "outputs": {"reference_answer": c.reference_answer},
        }
        for c in cases
    ]
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `cd backend && python -m pytest tests/test_evals.py -k "load_cases or to_examples" -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/evals/dataset.py backend/tests/test_evals.py
git commit -m "feat(evals): EvalCase schema, dataset loading and example projection"
```

---

### Task 3: Датасет `sql_cases.json` из отчёта

**Files:**
- Create: `backend/evals/datasets/sql_cases.json`
- Test: `backend/tests/test_evals.py` (дополнить проверкой реального файла)
- Read (источник данных): `problem-questions-report.html`, `sql_reqults.txt` (схемы колонок)

**Interfaces:**
- Consumes: `load_cases` из Task 2
- Produces: файл `sql_cases.json` с 5 кейсами, проходящий `load_cases`

- [ ] **Step 1: Извлечь кейсы из отчёта**

Открыть `problem-questions-report.html` и взять пять разделов, помеченных как готовые SQL-кейсы: `P0 — сравнение грейдов`, `P0 — Mobile`, `P1 — реестр сотрудников`, `P1 — Legal`, `Security gate — отпуск`. Для каждого выписать: точную формулировку вопроса (текст в «кавычках-ёлочках»), таблицу `toast_tbl_*`, `chunk_id` (если указан в разделе; иначе `chunk_<table-суффикс>`), «Проверенный ответ»/«Проверенный результат» как `reference_answer`.

`desc_vector` — одна строка-саммари назначения таблицы. `desc_full` — назначение + перечень колонок таблицы из `sql_reqults.txt` (схемы `information_schema.columns` уже выгружены там по трём таблицам; для остальных взять имена колонок из соответствующего раздела отчёта).

- [ ] **Step 2: Записать `backend/evals/datasets/sql_cases.json`**

Массив из 5 объектов по контракту из «File Structure». Пример одной записи (Legal — заполнить реальными значениями остальные четыре по тому же образцу):
```json
[
  {
    "question": "Какие ФИО у юристов Адвентум?",
    "chunk_id": "chunk_ec48a6d5",
    "table": "toast_tbl_ec48a6d52d16ab405f95",
    "desc_vector": "Юристы Adventum: ФИО и должности",
    "desc_full": "Таблица юристов Adventum. Колонки: _splitter_row_number, _splitter_source_row, _splitter_source_range, column_1, column_2, senior_legal_manager, column_4",
    "reference_answer": "Суворова Юлия Александровна, …"
  }
]
```

- [ ] **Step 3: Написать тест валидации реального файла**

Дополнить `backend/tests/test_evals.py`:
```python
from pathlib import Path

DATASET_PATH = Path(__file__).resolve().parent.parent / "evals" / "datasets" / "sql_cases.json"


def test_real_dataset_loads_and_is_complete():
    cases = load_cases(DATASET_PATH)
    assert len(cases) == 5
    for c in cases:
        assert c.table.startswith("toast_tbl_")
        assert c.question.strip()
        assert c.reference_answer.strip()
        assert c.desc_full.strip()
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `cd backend && python -m pytest tests/test_evals.py -k real_dataset -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/evals/datasets/sql_cases.json backend/tests/test_evals.py
git commit -m "feat(evals): SQL eval dataset extracted from problem-questions report"
```

---

### Task 4: Детерминированные оценщики

**Files:**
- Create: `backend/evals/evaluators.py` (первая часть — эвристики)
- Test: `backend/tests/test_evals.py` (дополнить)

**Interfaces:**
- Produces: `executes_ok(outputs: dict) -> dict`, `status_ok(outputs: dict) -> dict`, `has_rows(outputs: dict) -> dict`
- Каждый возвращает `{"key": <str>, "score": 0|1}`
- Consumes: контракт output `run_sql_tool` — ключи `status`, `rows_used`, `sql_attempts` (список `{"sql","ok","error","row_count"}`)

- [ ] **Step 1: Написать падающие тесты эвристик**

Дополнить `backend/tests/test_evals.py`:
```python
from evals.evaluators import executes_ok, has_rows, status_ok

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
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd backend && python -m pytest tests/test_evals.py -k "executes_ok or status_ok or has_rows" -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'evals.evaluators'`

- [ ] **Step 3: Реализовать эвристики**

Создать `backend/evals/evaluators.py`:
```python
"""Оценщики eval-харнесса.

Детерминированные эвристики над проекцией run_sql_tool + LLM-judge
корректности с фиксированной моделью-судьёй. langsmith биндит аргументы
оценщиков по имени параметра (outputs / inputs / reference_outputs).
"""


def executes_ok(outputs: dict) -> dict:
    """Хоть один SQL дошёл до БД без ошибки."""
    ok = any(a["ok"] for a in outputs.get("sql_attempts", []))
    return {"key": "executes_ok", "score": int(ok)}


def status_ok(outputs: dict) -> dict:
    """Инструмент завершился статусом ok (а не no_data / error)."""
    return {"key": "status_ok", "score": int(outputs.get("status") == "ok")}


def has_rows(outputs: dict) -> dict:
    """Итоговый ответ опирался хотя бы на одну строку."""
    return {"key": "has_rows", "score": int(outputs.get("rows_used", 0) > 0)}
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `cd backend && python -m pytest tests/test_evals.py -k "executes_ok or status_ok or has_rows" -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/evals/evaluators.py backend/tests/test_evals.py
git commit -m "feat(evals): deterministic heuristic evaluators"
```

---

### Task 5: LLM-judge корректности

**Files:**
- Modify: `backend/evals/evaluators.py` (добавить judge)
- Test: `backend/tests/test_evals.py` (дополнить)

**Interfaces:**
- Produces: `make_answer_correct(judge_model: BaseChatModel) -> Callable` — возвращает async-оценщик `answer_correct(inputs, outputs, reference_outputs) -> dict` с `{"key": "answer_correct", "score": 0|1, "comment": str}`
- Produces: `JudgeCorrectness(BaseModel)` с полями `correct: bool`, `reason: str`
- Produces: `judge_correctness(model, question, answer, reference) -> JudgeCorrectness`
- Consumes: фейки `StructuredScriptedChatModel`, `ScriptedChatModel` из `tests/fakes.py`

- [ ] **Step 1: Написать падающие тесты судьи**

Дополнить `backend/tests/test_evals.py`:
```python
import asyncio

from langchain_core.messages import AIMessage

from evals.evaluators import JudgeCorrectness, make_answer_correct
from tests.fakes import ScriptedChatModel, StructuredScriptedChatModel


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
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd backend && python -m pytest tests/test_evals.py -k answer_correct -v`
Expected: FAIL — `ImportError: cannot import name 'JudgeCorrectness'`

- [ ] **Step 3: Реализовать judge в evaluators.py**

В начало `backend/evals/evaluators.py` добавить импорты и модель, в конец — judge:
```python
import logging
import re
from collections.abc import Callable

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

logger = logging.getLogger(__name__)

_CORRECT_RE = re.compile(r"\bcorrect\b")  # \b: в "incorrect" не матчится

_JUDGE_SYS = (
    "Ты — придирчивый оценщик. Ответ считается верным, только если он "
    "содержит те же факты, что и эталон (числа, ФИО, значения совпадают по "
    "сути). Расхождение в формулировке допустимо, расхождение в фактах — нет."
)


class JudgeCorrectness(BaseModel):
    correct: bool
    reason: str = ""


async def judge_correctness(
    model: BaseChatModel, question: str, answer: str, reference: str
) -> JudgeCorrectness:
    """Вердикт судьи; structured output с текстовым фолбэком (как toast/llm.py)."""
    messages = [
        SystemMessage(_JUDGE_SYS),
        HumanMessage(
            f"Вопрос: {question}\nОтвет инструмента: {answer}\nЭталон: {reference}\n"
            "Верен ли ответ инструмента относительно эталона?"
        ),
    ]
    try:
        structured = model.with_structured_output(
            JudgeCorrectness, method="function_calling"
        )
        return await structured.ainvoke(messages)
    except Exception as e:
        logger.debug("judge: structured недоступен (%r), текстовый фолбэк", e)
        reply = await model.ainvoke(messages)
        text = str(reply.content).lower()
        ok = bool(_CORRECT_RE.search(text))
        return JudgeCorrectness(correct=ok, reason="")


def make_answer_correct(judge_model: BaseChatModel) -> Callable:
    """Async-оценщик корректности с фиксированной моделью-судьёй."""

    async def answer_correct(
        inputs: dict, outputs: dict, reference_outputs: dict
    ) -> dict:
        verdict = await judge_correctness(
            judge_model,
            inputs.get("question", ""),
            outputs.get("answer", ""),
            reference_outputs.get("reference_answer", ""),
        )
        return {
            "key": "answer_correct",
            "score": int(verdict.correct),
            "comment": verdict.reason,
        }

    return answer_correct
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `cd backend && python -m pytest tests/test_evals.py -k answer_correct -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/evals/evaluators.py backend/tests/test_evals.py
git commit -m "feat(evals): LLM-judge correctness evaluator with fixed judge model"
```

---

### Task 6: Синк датасета в LangSmith (идемпотентный)

**Files:**
- Modify: `backend/evals/dataset.py` (добавить `ensure_dataset`)
- Test: `backend/tests/test_evals.py` (дополнить, с фейковым клиентом)

**Interfaces:**
- Produces: `ensure_dataset(client, name: str, cases: list[EvalCase]) -> str` — возвращает `name`; создаёт датасет и примеры только если его ещё нет
- Consumes: `client.has_dataset(dataset_name=...) -> bool`, `client.create_dataset(dataset_name=...) -> obj(.id)`, `client.create_examples(dataset_id=..., examples=[...])`, `to_examples`

- [ ] **Step 1: Написать падающие тесты идемпотентности**

Дополнить `backend/tests/test_evals.py`:
```python
from evals.dataset import ensure_dataset


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
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd backend && python -m pytest tests/test_evals.py -k ensure_dataset -v`
Expected: FAIL — `ImportError: cannot import name 'ensure_dataset'`

- [ ] **Step 3: Реализовать ensure_dataset**

В конец `backend/evals/dataset.py` добавить:
```python
def ensure_dataset(client, name: str, cases: list[EvalCase]) -> str:
    """Идемпотентно завести датасет в LangSmith. Существует — не трогаем.

    Первая заливка создаёт датасет и примеры; повторные прогоны просто
    переиспользуют его по имени (чтобы не плодить дубли примеров).
    """
    if client.has_dataset(dataset_name=name):
        return name
    dataset = client.create_dataset(dataset_name=name)
    client.create_examples(dataset_id=dataset.id, examples=to_examples(cases))
    return name
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `cd backend && python -m pytest tests/test_evals.py -k ensure_dataset -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/evals/dataset.py backend/tests/test_evals.py
git commit -m "feat(evals): idempotent LangSmith dataset sync"
```

---

### Task 7: CLI-обвязка `run_sql_eval.py`

**Files:**
- Create: `backend/evals/run_sql_eval.py`
- Test: `backend/tests/test_evals.py` (дополнить оффлайн-тестом target)

**Interfaces:**
- Produces: `make_target(model, executor, settings) -> Callable[[dict], Awaitable[dict]]`
- Produces: `parse_args(argv=None) -> argparse.Namespace` с полями `models: list[str]`, `judge_model: str`, `dataset_name: str`, `limit: int | None`, `max_concurrency: int`
- Produces: `async def main(argv=None) -> None`
- Consumes: `run_sql_tool` (toast.sql_tool), `PgExecutor` (toast.executor), `build_eval_model`, `load_cases`, `ensure_dataset`, оценщики, `langsmith.aevaluate`, `langsmith.Client`

- [ ] **Step 1: Написать падающий оффлайн-тест target и парсера**

Дополнить `backend/tests/test_evals.py`:
```python
from langchain_core.messages import AIMessage

from evals.run_sql_eval import make_target, parse_args
from tests.graph_utils import FakeExecutor, _ok_attempt  # noqa: F401
from toast.models import SqlCandidates


def test_parse_args_splits_models():
    ns = parse_args(["--models", "openai/gpt-4o, anthropic/claude-sonnet-4.6"])
    assert ns.models == ["openai/gpt-4o", "anthropic/claude-sonnet-4.6"]


def test_make_target_runs_graph_offline(monkeypatch):
    settings = _settings(monkeypatch)
    # сэмпл (run_select #1) + один исполненный кандидат (run_select #2)
    sample = {"columns": ["column_1"], "rows": [{"column_1": "x"}],
              "row_count": 1, "truncated": False}
    rows = {"columns": ["column_1"], "rows": [{"column_1": "Суворова"}],
            "row_count": 1, "truncated": False}
    executor = FakeExecutor([sample, rows])
    model = StructuredScriptedChatModel(responses=[
        SqlCandidates(candidates=["SELECT column_1 FROM t"]),  # generate
        JudgeCorrectness(correct=True, reason=""),             # (не используется judge графа)
        AIMessage("Суворова Юлия Александровна"),              # summarize
    ])
    target = make_target(model, executor, settings)
    out = asyncio.run(target({
        "question": "ФИО юристов?",
        "chunk_id": "c1",
        "table": "toast_tbl_ec48a6d52d16ab405f95",
        "desc_vector": "юристы",
        "desc_full": "Таблица юристов",
    }))
    assert out["status"] == "ok"
    assert "sql_attempts" in out
```

Примечание: точный список `responses` фейка сверить с тем, как граф зовёт модель (generate → judge → summarize) — при необходимости подогнать под сценарий из `tests/test_graph_flow.py`.

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd backend && python -m pytest tests/test_evals.py -k "parse_args or make_target" -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'evals.run_sql_eval'`

- [ ] **Step 3: Реализовать CLI**

Создать `backend/evals/run_sql_eval.py`:
```python
"""CLI eval-харнесса: прогон SQL-инструмента по моделям в LangSmith.

Пример:
    cd backend && python -m evals.run_sql_eval \
        --models "openai/gpt-4o, anthropic/claude-sonnet-4.6"

Требует окружения: OPENROUTER_API_KEY, TOAST_DB_*, LANGSMITH_ENDPOINT/
LANGSMITH_API_KEY (self-hosted). Латентность и токены LangSmith снимает из
трейсов автоматически.
"""

import argparse
import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path

from langsmith import Client, aevaluate

from config import get_settings
from evals.dataset import ensure_dataset, load_cases
from evals.evaluators import executes_ok, has_rows, make_answer_correct, status_ok
from evals.models import build_eval_model
from toast.executor import PgExecutor
from toast.sql_tool import run_sql_tool

DATASET_PATH = Path(__file__).resolve().parent / "datasets" / "sql_cases.json"
DEFAULT_DATASET_NAME = "sql-tool-eval"


def make_target(model, executor, settings) -> Callable[[dict], Awaitable[dict]]:
    """Async-target для aevaluate: прогон одного примера через run_sql_tool."""

    async def target(inputs: dict) -> dict:
        return await run_sql_tool(
            inputs, model, executor,
            settings.sql_max_queries, settings.sql_candidates_per_round,
        )

    return target


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Eval SQL-инструмента по моделям")
    p.add_argument("--models", required=True,
                   help="OpenRouter-модели через запятую")
    p.add_argument("--judge-model", default=None,
                   help="модель-судья (по умолчанию EVAL_JUDGE_MODEL)")
    p.add_argument("--dataset-name", default=DEFAULT_DATASET_NAME)
    p.add_argument("--limit", type=int, default=None,
                   help="ограничить число кейсов (для дымового прогона)")
    p.add_argument("--max-concurrency", type=int, default=4)
    ns = p.parse_args(argv)
    ns.models = [m.strip() for m in ns.models.split(",") if m.strip()]
    return ns


async def main(argv=None) -> None:
    args = parse_args(argv)
    settings = get_settings()
    if settings.toast_dsn is None:
        raise SystemExit("TOAST_DB_* обязателен для eval (доступ к splitter_toast.*)")

    cases = load_cases(DATASET_PATH)
    if args.limit is not None:
        cases = cases[: args.limit]

    client = Client()  # LANGSMITH_ENDPOINT / LANGSMITH_API_KEY из окружения
    ensure_dataset(client, args.dataset_name, cases)

    executor = PgExecutor(settings.toast_dsn)
    judge = build_eval_model(
        args.judge_model or settings.eval_judge_model, settings, temperature=0.0
    )
    evaluators = [executes_ok, status_ok, has_rows, make_answer_correct(judge)]

    for model_name in args.models:
        model = build_eval_model(model_name, settings)
        await aevaluate(
            make_target(model, executor, settings),
            data=args.dataset_name,
            evaluators=evaluators,
            experiment_prefix=model_name,
            client=client,
            max_concurrency=args.max_concurrency,
        )
        print(f"готово: {model_name}")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 4: Запустить — убедиться, что проходит (и весь файл целиком)**

Run: `cd backend && python -m pytest tests/test_evals.py -v`
Expected: PASS (все тесты eval-харнесса зелёные)

- [ ] **Step 5: Commit**

```bash
git add backend/evals/run_sql_eval.py backend/tests/test_evals.py
git commit -m "feat(evals): run_sql_eval CLI wiring target and aevaluate loop"
```

---

### Task 8: Документация и реестр окружения

**Files:**
- Create: `docs/evals.md`
- Modify: `.env.example` (добавить LangSmith-переменные и EVAL_JUDGE_MODEL)
- Modify: `backend/config.py` (комментарий-реестр про LangSmith-passthrough)

**Interfaces:**
- Consumes: всё готовое из Task 1–7

- [ ] **Step 1: Написать `docs/evals.md`**

Создать `docs/evals.md`:
```markdown
# Eval-харнесс SQL-инструмента (LangSmith self-hosted)

Прогон `toast` на фиксированном датасете вопросов с разными OpenRouter-моделями
и сравнение в self-hosted LangSmith.

## Окружение

- `OPENROUTER_API_KEY` — ключ OpenRouter.
- `TOAST_DB_HOST/PORT/USER/PASSWORD/NAME` — доступ к реальным `splitter_toast.*`.
- `LANGSMITH_ENDPOINT` — URL self-hosted инстанса LangSmith.
- `LANGSMITH_API_KEY` — ключ инстанса.
- `LANGSMITH_TRACING=true` — включает трейсинг узлов графа.
- `EVAL_JUDGE_MODEL` — фиксированная модель-судья (по умолчанию `anthropic/claude-sonnet-4.6`).

## Запуск

    cd backend
    python -m evals.run_sql_eval --models "openai/gpt-4o, anthropic/claude-sonnet-4.6"

Флаги: `--judge-model`, `--dataset-name` (по умолчанию `sql-tool-eval`),
`--limit N` (дымовой прогон), `--max-concurrency`.

## Что смотреть в LangSmith

Каждой модели соответствует эксперимент с префиксом-именем модели. Метрики
оценщиков: `executes_ok`, `status_ok`, `has_rows`, `answer_correct`. Латентность
и токены/стоимость LangSmith берёт из трейсов автоматически. Сравнение
экспериментов бок о бок — во вкладке датасета `sql-tool-eval`.

## Датасет

`backend/evals/datasets/sql_cases.json` — 5 кейсов из
`problem-questions-report.html`. Поля `inputs` совпадают с `SqlToolInput`,
`outputs.reference_answer` — эталон для судьи. Первый прогон заливает датасет в
LangSmith; повторные переиспользуют по имени.
```

- [ ] **Step 2: Дополнить `.env.example`**

В конец `.env.example` добавить блок:
```bash
# --- Eval-харнесс (LangSmith self-hosted) ---
# Читают langsmith SDK (LANGSMITH_*) и config.py (EVAL_JUDGE_MODEL).
LANGSMITH_TRACING=true
LANGSMITH_ENDPOINT=
LANGSMITH_API_KEY=
EVAL_JUDGE_MODEL=anthropic/claude-sonnet-4.6
```

- [ ] **Step 3: Отметить LangSmith-passthrough в реестре config.py**

В `backend/config.py`, в секции passthrough-полей (после `oauth_generic_*`, где перечислены поля «читает сам Chainlit»), добавить комментарий:
```python
    # LANGSMITH_ENDPOINT / LANGSMITH_API_KEY / LANGSMITH_TRACING читает сам
    # langsmith SDK из окружения — здесь не дублируем (нужны только eval-скрипту).
```

- [ ] **Step 4: Прогнать весь набор тестов бэкенда — регрессий нет**

Run: `cd backend && python -m pytest -q`
Expected: все тесты зелёные (включая существующие agents/graph/oauth и новые evals)

- [ ] **Step 5: Commit**

```bash
git add docs/evals.md .env.example backend/config.py
git commit -m "docs(evals): usage guide and LangSmith env registry"
```

---

## Self-Review

**1. Spec coverage:**
- LangSmith self-hosted → Task 7 (`Client()` + env), Task 8 (env-реестр). ✓
- Только OpenRouter → Task 1 (`build_eval_model`), Global Constraints. ✓
- Датасет из report → Task 3. ✓
- Эвристика + LLM-judge → Task 4, Task 5. ✓
- Судья фиксирован (`EVAL_JUDGE_MODEL`) → Task 1 (конфиг), Task 5 (инъекция), Task 7 (сборка). ✓
- desc_vector/desc_full вручную → Task 3, контракт `sql_cases.json`. ✓
- Раскладка `backend/evals/` → File Structure, Task 1–7. ✓
- `toast/` не трогаем → Global Constraints; обёртка `make_target` в Task 7. ✓
- Тесты на фейках без сети → Task 1–7 (все тесты используют fakes/graph_utils/фейк-клиент). ✓
- Ранний выход без окружения → Task 7 (`toast_dsn is None`), Task 1 (нет ключа). ✓
- Зависимость langsmith → Task 1. ✓
- latency/токены из трейсов → Task 8 (доки), кода не требуют. ✓

**2. Placeholder scan:** реальный код во всех шагах; единственный «дозаполняемый» артефакт — данные `sql_cases.json` (Task 3), у него явный источник (разделы отчёта) и валидационный гейт (тест на 5 кейсов). Тест target (Task 7) содержит примечание сверить `responses` со сценарием `test_graph_flow.py` — это исполнимая инструкция, не заглушка.

**3. Type consistency:** `build_eval_model(name, settings, temperature)` — единая сигнатура в Task 1/5/7. `EvalCase`/`load_cases`/`to_examples`/`ensure_dataset` согласованы Task 2↔6. Оценщики возвращают `{"key","score"[,"comment"]}` во всех задачах. `make_target(model, executor, settings)` совпадает в Task 7 и тесте. Ключи output (`status`, `rows_used`, `sql_attempts`) соответствуют `_project` из `toast/sql_tool.py`.
