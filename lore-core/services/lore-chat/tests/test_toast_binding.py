"""toast_binding: SqlRequest -> toast graph -> SQLResult mapping (on fakes)."""
import asyncio

import toast_binding
from lore_retrieval.contracts import SQLStatus, SqlRequest
from lore_retrieval.source import SourceChunk


def _chunk():
    return SourceChunk(
        chunk_id="e6", document_id="d", run_id="r", chunk_type="table_payload", position=0,
        heading_path=(), vector_text="юристы", fulltext="Реестр юристов. column_1 — ФИО",
        payload_refs=[{"payload_id": "toast_tbl_x"}], vector_text_hash="h", fulltext_hash="h",
    )


class _FakeLoader:
    def __init__(self, chunk):
        self._c = chunk

    async def load(self, ids):
        return [self._c] if self._c else []


class _FakeGraph:
    def __init__(self, state):
        self._state = state
        self.last_input = None

    async def ainvoke(self, inp):
        self.last_input = inp
        return self._state


_DEFAULT = object()


def _wire(monkeypatch, state, chunk=_DEFAULT):
    graph = _FakeGraph(state)
    monkeypatch.setattr(toast_binding, "_graph", graph)
    monkeypatch.setattr(toast_binding, "_loader", _FakeLoader(_chunk() if chunk is _DEFAULT else chunk))
    return graph


def _req():
    return SqlRequest(question="Какие ФИО у юристов?", payload_id="toast_tbl_x", chunk_id="e6")


def test_ok_state_maps_to_success_with_rows(monkeypatch):
    graph = _wire(monkeypatch, {
        "status": "ok",
        "answer": "Каневский Георгий Георгиевич — Помощник Юриста",
        "attempts": [{"ok": True, "rows": [{"column_1": "Каневский", "column_2": "Помощник Юриста"}]}],
    })
    res = asyncio.run(toast_binding._run(_req()))
    assert res.status == SQLStatus.success
    assert res.answer_summary.startswith("Каневский")
    assert res.rows == [{"column_1": "Каневский", "column_2": "Помощник Юриста"}]
    # table = trusted payload_id; desc_full = chunk fulltext (passed in Studio format)
    assert graph.last_input["table"] == "toast_tbl_x"
    assert graph.last_input["desc_full"].startswith("Реестр юристов")


def test_no_data_maps_to_empty(monkeypatch):
    _wire(monkeypatch, {"status": "no_data", "answer": "Данных нет", "attempts": [{"ok": True, "rows": []}]})
    res = asyncio.run(toast_binding._run(_req()))
    assert res.status == SQLStatus.empty
    assert res.rows == []


def test_error_maps_to_execution_error(monkeypatch):
    _wire(monkeypatch, {"status": "error", "answer": "Не удалось выполнить SQL", "attempts": []})
    res = asyncio.run(toast_binding._run(_req()))
    assert res.status == SQLStatus.execution_error
    assert res.error == "Не удалось выполнить SQL"


def test_missing_chunk_is_not_applicable(monkeypatch):
    _wire(monkeypatch, {}, chunk=None)
    res = asyncio.run(toast_binding._run(_req()))
    assert res.status == SQLStatus.not_applicable
    assert res.rows == []
