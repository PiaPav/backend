"""AST expression conversion helpers."""

from __future__ import annotations

import ast
from typing import Any


def dotted_name(node: ast.AST | None) -> str:
    """Return a stable syntactic name for names and attribute chains."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = dotted_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ast.unparse(node) if node is not None else ""


def annotation_value(node: ast.expr | None) -> Any:
    """Convert an annotation to the compact type format used by the graph."""
    if node is None:
        return None
    if isinstance(node, ast.Subscript):
        parent = dotted_name(node.value)
        child_node = node.slice
        if isinstance(child_node, ast.Tuple):
            child: Any = ", ".join(ast.unparse(item) for item in child_node.elts)
        else:
            child = annotation_value(child_node)
        return {"parent": parent, "child": child}
    return ast.unparse(node)


def simple_value(node: ast.expr | None) -> Any:
    """Convert simple values while retaining unsupported expressions as source."""
    if node is None:
        return None
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.operand, ast.Constant):
        try:
            return ast.literal_eval(node)
        except (ValueError, TypeError):
            pass
    return ast.unparse(node)


def infer_literal_type(node: ast.expr | None) -> str | None:
    if isinstance(node, ast.Constant):
        return type(node.value).__name__
    if isinstance(node, ast.List):
        return "list"
    if isinstance(node, ast.Tuple):
        return "tuple"
    if isinstance(node, ast.Dict):
        return "dict"
    if isinstance(node, ast.Set):
        return "set"
    return None
