from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Any, Dict

try:
    import celpy
except Exception:  # pragma: no cover - optional dependency
    celpy = None

CELPY_AVAILABLE = celpy is not None


class EvaluationError(RuntimeError):
    pass


@dataclass
class ExpressionContext:
    inputs: Dict[str, Any]
    state: Dict[str, Any]
    node_outputs: Dict[str, Any]


class ExpressionEvaluator:
    def eval(self, expression: str, context: ExpressionContext) -> Any:
        raise NotImplementedError


class CelEvaluator(ExpressionEvaluator):
    def __init__(self) -> None:
        if celpy is None:
            raise RuntimeError("cel-python is not installed")
        self._env = celpy.Environment()
        self._program_cache: Dict[str, Any] = {}

    def eval(self, expression: str, context: ExpressionContext) -> Any:
        try:
            program = self._program_cache.get(expression)
            if program is None:
                ast = self._env.compile(expression)
                program = self._env.program(ast)
                self._program_cache[expression] = program
            activation = {
                "inputs": celpy.json_to_cel(context.inputs),
                "state": celpy.json_to_cel(context.state),
                "node_outputs": celpy.json_to_cel(context.node_outputs),
            }
            return program.evaluate(activation)
        except Exception as exc:  # CELSyntaxError, EvalError, etc.
            raise EvaluationError(str(exc)) from exc


class SimpleEvaluator(ExpressionEvaluator):
    """A minimal, safe evaluator for tests. This is NOT full CEL.

    Supported operators: ==, !=, >, <, >=, <=, and/or/not
    Supports dotted access via names: inputs, state, node_outputs
    """

    _allowed_nodes = (
        ast.Expression,
        ast.BoolOp,
        ast.BinOp,
        ast.UnaryOp,
        ast.Compare,
        ast.Name,
        ast.Load,
        ast.Constant,
        ast.And,
        ast.Or,
        ast.Not,
        ast.Eq,
        ast.NotEq,
        ast.Gt,
        ast.GtE,
        ast.Lt,
        ast.LtE,
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.Mod,
        ast.Subscript,
        ast.Index,
        ast.Attribute,
        ast.Dict,
        ast.List,
        ast.Tuple,
    )

    def eval(self, expression: str, context: ExpressionContext) -> Any:
        try:
            tree = ast.parse(expression, mode="eval")
        except SyntaxError as exc:
            raise EvaluationError(str(exc)) from exc

        for node in ast.walk(tree):
            if not isinstance(node, self._allowed_nodes):
                raise EvaluationError(f"Unsupported expression node: {type(node).__name__}")

        env = {
            "inputs": context.inputs,
            "state": context.state,
            "node_outputs": context.node_outputs,
        }

        return eval(compile(tree, "<expr>", "eval"), {"__builtins__": {}}, env)
