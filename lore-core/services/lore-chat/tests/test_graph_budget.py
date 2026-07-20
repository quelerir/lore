from langchain_core.messages import AIMessage

from fakes import ScriptedChatModel
from graph_utils import (
    LEGAL, FakeExecutor, _rows, _run, _sample,
)
from toast.models import Refusal



def test_budget_exhausted_no_data():
    # Все кандидаты возвращают 0 строк. Судья при пустом результате НЕ зовёт
    # модель (короткое замыкание в need_more), поэтому скриптуем только 3
    # ответа generate. Бюджет исчерпан -> no_data. SQL в раундах разные —
    # повторы не выполняются (дедупликация), но бюджет списывают.
    model = ScriptedChatModel(responses=[
        AIMessage(content='["SELECT column_1 FROM %s"]' % LEGAL),
        AIMessage(content='["SELECT column_2 FROM %s"]' % LEGAL),
        AIMessage(content='["SELECT column_3 FROM %s"]' % LEGAL),
    ])
    exe = FakeExecutor(results=[_sample(), _rows(0), _rows(0), _rows(0)])
    out = _run(model, exe, candidates=1, max_queries=3)
    assert out["status"] == "no_data"
    assert len(exe.calls) == 4  # сэмпл + 3 кандидата



def test_duplicate_candidates_stopped_by_round_cap():
    # Повтор SQL не гоняется в БД и бюджет НЕ двигает — цикл останавливает
    # предел раундов (== max_queries).
    model = ScriptedChatModel(responses=[
        AIMessage(content='["SELECT column_1 FROM %s"]' % LEGAL),
        AIMessage(content='["SELECT column_1 FROM %s"]' % LEGAL),  # дубликат
        AIMessage(content='["SELECT column_1 FROM %s"]' % LEGAL),  # дубликат
    ])
    exe = FakeExecutor(results=[_sample(), _rows(0)])
    out = _run(model, exe, candidates=1, max_queries=3)
    assert out["status"] == "no_data"
    assert len(exe.calls) == 2  # сэмпл + один реальный SELECT



def test_guardrails_refusal_does_not_consume_budget():
    # Раунд 1: два кандидата — отказ валидатора + удачный SELECT. Отказ не
    # списывается → executed=1 < 2 → зовётся СУДЬЯ. При старой семантике
    # executed=2 исчерпал бы бюджет, judge был бы пропущен, и summarize
    # съел бы заскриптованный "SUFFICIENT" как ответ — ассерт на answer
    # ловит разницу.
    model = ScriptedChatModel(responses=[
        AIMessage(content='["DROP TABLE x", "SELECT column_1 FROM %s"]' % LEGAL),
        AIMessage(content="SUFFICIENT"),
        AIMessage(content="Ответ."),
    ])
    exe = FakeExecutor(results=[_sample(), Refusal("Отказ: разрешён только SELECT."),
                                _rows(1)])
    out = _run(model, exe, candidates=2, max_queries=2)
    assert out["status"] == "ok"
    assert out["answer"] == "Ответ."



def test_round_cap_stops_refusal_only_batches():
    # Модель упорно генерит запрещённое: бюджет не тратится, но предел
    # раундов (== max_queries) останавливает цикл со status=error.
    model = ScriptedChatModel(responses=[
        AIMessage(content='["DROP TABLE x"]'),
        AIMessage(content='["DROP TABLE y"]'),
    ])
    exe = FakeExecutor(results=[_sample(), Refusal("Отказ: разрешён только SELECT."),
                                Refusal("Отказ: разрешён только SELECT.")])
    out = _run(model, exe, candidates=1, max_queries=2)
    assert out["status"] == "error"
    assert "Отказ" in out["answer"]



def test_sample_not_counted_in_budget():
    # max_queries=1: сэмпл вне бюджета, кандидат всё ещё выполняется.
    model = ScriptedChatModel(responses=[
        AIMessage(content='["SELECT column_1 FROM %s"]' % LEGAL),
        AIMessage(content="Ответ."),  # summarize (бюджет исчерпан, судьи нет)
    ])
    exe = FakeExecutor(results=[_sample(), _rows(1)])
    out = _run(model, exe, candidates=1, max_queries=1)
    assert out["status"] == "ok"
    assert len(exe.calls) == 2
