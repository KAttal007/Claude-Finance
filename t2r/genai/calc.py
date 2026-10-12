"""Deterministic arithmetic for the model (design doc 11.2 ``calc``): growth, margins, variances
are computed here in Decimal, never by the model. A tiny AST evaluator, no eval()."""

import ast
import operator
from collections.abc import Callable
from decimal import Decimal, DivisionByZero, InvalidOperation, getcontext
from typing import Any

getcontext().prec = 28

_BIN: dict[type[ast.operator], Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
}
_UNARY: dict[type[ast.unaryop], Callable[[Any], Any]] = {
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}
_FUNCS: dict[str, Callable[..., Any]] = {
    "abs": abs,
    "min": min,
    "max": max,
    "round": lambda x, n=0: round(x, int(n)),
}


class CalcError(ValueError):
    pass


def calc(expression: str, inputs: dict[str, Any] | None = None) -> Decimal:
    names = {k: Decimal(str(v)) for k, v in (inputs or {}).items()}
    try:
        tree = ast.parse(expression, mode="eval")
        return _eval(tree.body, names)
    except (SyntaxError, InvalidOperation, DivisionByZero, ZeroDivisionError) as exc:
        raise CalcError(f"cannot evaluate {expression!r}: {exc}") from exc


def _eval(node: ast.AST, names: dict[str, Decimal]) -> Decimal:
    if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
        return Decimal(str(node.value))
    if isinstance(node, ast.Name):
        if node.id not in names:
            raise CalcError(f"unknown input {node.id!r}")
        return names[node.id]
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
        if isinstance(node.op, ast.Pow):
            exp = _eval(node.right, names)
            if abs(exp) > 100:
                raise CalcError("exponent too large")
        return _BIN[type(node.op)](_eval(node.left, names), _eval(node.right, names))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_eval(node.operand, names))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS:
        return Decimal(str(_FUNCS[node.func.id](*[_eval(a, names) for a in node.args])))
    raise CalcError(f"unsupported expression element {ast.dump(node)[:60]}")
