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
