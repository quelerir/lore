
from graph_utils import (
    _fail_attempt, _ok_attempt,
)



def test_rows_context_groups_by_attempt():
    from toast.prompts import rows_context

    ctx = rows_context([
        _ok_attempt("SELECT a", [{"a": 1}]),
        _fail_attempt(),
        _ok_attempt("SELECT b", [{"b": 2}]),
    ])
    assert "Запрос: SELECT a" in ctx and "Запрос: SELECT b" in ctx
    assert "SELECT bad" not in ctx  # неуспешные попытки не в контексте
    assert "Показано строк: 2 из 2" in ctx



def test_rows_context_caps_by_size():
    from toast.prompts import JUDGE_CONTEXT_CHARS, rows_context

    big = _ok_attempt("SELECT big", [{"column_1": "x" * JUDGE_CONTEXT_CHARS}])
    small = _ok_attempt("SELECT small", [{"column_1": "y"}])
    ctx = rows_context([big, small])
    assert "Показано строк: 1 из 2" in ctx
    assert '"y"' not in ctx

    # Хотя бы одна строка отдаётся всегда, даже если сама больше лимита.
    ctx_one = rows_context([big])
    assert "Показано строк: 1 из 1" in ctx_one
