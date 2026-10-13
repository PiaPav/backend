"""Static complexity and exception facts for one function AST."""

from __future__ import annotations

import ast

from .models import FunctionMetricsInfo


class _MetricsVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.cyclomatic = 1
        self.cognitive = 0
        self.nesting = 0
        self.max_nesting = 0
        self.statements = 0
        self.returns = 0
        self.raises = 0
        self.awaits = 0
        self.broad_handlers = 0
        self.raised: set[str] = set()
        self.caught: set[str] = set()
        self.self_attributes: set[str] = set()

    def visit(self, node: ast.AST):  # type: ignore[override]
        if isinstance(node, ast.stmt):
            self.statements += 1
        return super().visit(node)

    def _control(self, node: ast.AST, *, cyclomatic: int = 1) -> None:
        self.cyclomatic += cyclomatic
        self.cognitive += 1 + self.nesting
        self.nesting += 1
        self.max_nesting = max(self.max_nesting, self.nesting)
        self.generic_visit(node)
        self.nesting -= 1

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return

    def visit_If(self, node: ast.If) -> None:
        self._control(node)

    def visit_For(self, node: ast.For) -> None:
        self._control(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self._control(node)

    def visit_While(self, node: ast.While) -> None:
        self._control(node)

    def visit_Try(self, node: ast.Try) -> None:
        self._control(node, cyclomatic=0)

    def visit_TryStar(self, node: ast.TryStar) -> None:
        self._control(node, cyclomatic=0)

    def visit_Match(self, node: ast.Match) -> None:
        self._control(node, cyclomatic=max(1, len(node.cases) - 1))

    def visit_IfExp(self, node: ast.IfExp) -> None:
        self._control(node)

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        decisions = max(0, len(node.values) - 1)
        self.cyclomatic += decisions
        self.cognitive += decisions
        self.generic_visit(node)

    def visit_comprehension(self, node: ast.comprehension) -> None:
        decisions = 1 + len(node.ifs)
        self.cyclomatic += decisions
        self.cognitive += decisions + self.nesting
        self.nesting += 1
        self.max_nesting = max(self.max_nesting, self.nesting)
        self.generic_visit(node)
        self.nesting -= 1

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        self.cyclomatic += 1
        self.cognitive += 1 + self.nesting
        if node.type is None:
            self.broad_handlers += 1
            self.caught.add("bare except")
        else:
            name = ast.unparse(node.type)
            self.caught.add(name)
            if name in {"Exception", "BaseException"}:
                self.broad_handlers += 1
        self.generic_visit(node)

    def visit_Return(self, node: ast.Return) -> None:
        self.returns += 1
        self.generic_visit(node)

    def visit_Raise(self, node: ast.Raise) -> None:
        self.raises += 1
        if node.exc is not None:
            target = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
            self.raised.add(ast.unparse(target))
        self.generic_visit(node)

    def visit_Await(self, node: ast.Await) -> None:
        self.awaits += 1
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if isinstance(node.value, ast.Name) and node.value.id == "self":
            self.self_attributes.add(node.attr)
        self.generic_visit(node)


def analyze_function_metrics(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> FunctionMetricsInfo:
    visitor = _MetricsVisitor()
    for statement in node.body:
        visitor.visit(statement)
    end_line = getattr(node, "end_lineno", None) or node.lineno
    return FunctionMetricsInfo(
        cyclomatic_complexity=visitor.cyclomatic,
        cognitive_complexity=visitor.cognitive,
        max_nesting=visitor.max_nesting,
        lines_of_code=max(1, end_line - node.lineno + 1),
        statement_count=visitor.statements,
        return_count=visitor.returns,
        raise_count=visitor.raises,
        await_count=visitor.awaits,
        broad_exception_handlers=visitor.broad_handlers,
        raised_exceptions=sorted(visitor.raised),
        caught_exceptions=sorted(visitor.caught),
        self_attribute_accesses=sorted(visitor.self_attributes),
        is_async=isinstance(node, ast.AsyncFunctionDef),
    )
