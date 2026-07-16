"""Инструменты агента: пока только калькулятор.

SQL-инструмент над toast-таблицами вынесен в отдельный граф (toast/), он не
вызывается чат-агентом и подключается будущим пайплайном отдельно.
"""

import ast
import operator

from langchain_core.tools import BaseTool, tool

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


def make_tools() -> list[BaseTool]:
    return [calculator]
