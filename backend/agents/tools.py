"""Инструменты, общие для обоих режимов агента: калькулятор и toast-субагент."""

import ast
import json
import operator

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import BaseTool, tool

from toast.port import ToastStorePort
from toast.subagent import run_toast_subagent

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_MAX_POW = 10_000


def _eval_node(node: ast.expr) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return _UNARY_OPS[type(node.op)](_eval_node(node.operand))
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        left, right = _eval_node(node.left), _eval_node(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > _MAX_POW:
            raise ValueError("слишком большая степень")
        return _BIN_OPS[type(node.op)](left, right)
    raise ValueError(f"недопустимая конструкция: {ast.dump(node)[:60]}")


def evaluate_expression(expression: str) -> float:
    """Безопасная арифметика через AST — никакого eval."""
    tree = ast.parse(expression.strip(), mode="eval")
    return _eval_node(tree.body)


@tool
def calculator(expression: str) -> str:
    """Вычислить арифметическое выражение.

    Поддерживает числа, + - * / // % **, скобки и унарный минус.
    Пример: "(17 + 3) * 4 / 2". Используй для любых вычислений —
    не считай в уме.
    """
    try:
        result = evaluate_expression(expression)
    except ZeroDivisionError:
        return "Ошибка: деление на ноль."
    except (ValueError, SyntaxError) as e:
        return f"Ошибка: не удалось вычислить выражение ({e})."
    if isinstance(result, float) and result.is_integer():
        result = int(result)
    return str(result)


def _make_query_document_tables(
    model: BaseChatModel, store: ToastStorePort
) -> BaseTool:
    @tool
    async def query_document_tables(question: str) -> str:
        """Найти ответ на вопрос в таблицах из внутренних документов.

        Используй для вопросов о сотрудниках, отделах, грейдах,
        компетенциях и содержимом рабочих файлов. Передавай вопрос
        целиком. Возвращает JSON: status (ok|no_table|refused|error),
        rows, sql, sources (файл и таблица — укажи их в ответе),
        header_hints (записи, потерянные при извлечении — тоже источник
        данных, не теряй их).
        """
        # Ошибки соединения с БД не PostgresError и не ловятся в store —
        # спека требует status=error, а не исключение из инструмента.
        try:
            result = await run_toast_subagent(model, store, question)
        except Exception as e:  # noqa: BLE001 — граница инструмента
            result = {"status": "error", "message": f"техническая ошибка: {e}"}
        return json.dumps(result, ensure_ascii=False, default=str)

    return query_document_tables


def make_tools(
    model: BaseChatModel | None = None,
    store: ToastStorePort | None = None,
) -> list[BaseTool]:
    tools: list[BaseTool] = [calculator]
    if model is not None and store is not None:
        tools.append(_make_query_document_tables(model, store))
    return tools
