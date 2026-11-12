"""Static complexity and exception facts for one function AST."""

from __future__ import annotations

import ast

from .models import (
    ComplexityControlFact,
    ComplexityOccurrenceFact,
    FunctionComplexityFacts,
    FunctionMetricsInfo,
)


class _FactsVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.controls: list[ComplexityControlFact] = []
        self.occurrences: list[ComplexityOccurrenceFact] = []
        self.parents: list[int] = []
        self.locations: list[tuple[int, int]] = []

    def _location(self, node: ast.AST) -> tuple[int, int]:
        """Use the nearest located syntax node for location-less AST structure."""
        line = getattr(node, "lineno", None)
        column = getattr(node, "col_offset", None)
        if line is not None and column is not None:
            return line, column
        if self.locations:
            return self.locations[-1]
        raise ValueError(f"No source location available for {type(node).__name__}")

    def _occurrence(self, kind: str, node: ast.AST, expression: str | None = None) -> None:
        self.occurrences.append(ComplexityOccurrenceFact(
            kind, node.lineno, node.col_offset, expression  # type: ignore[attr-defined]
        ))

    def visit(self, node: ast.AST):  # type: ignore[override]
        location = self._location(node)
        self.locations.append(location)
        if isinstance(node, ast.stmt):
            self._occurrence("statement", node)
        try:
            return super().visit(node)
        finally:
            self.locations.pop()

    def _control(self, node: ast.AST, kind: str, **cardinality: int) -> None:
        index = len(self.controls)
        line, column = self._location(node)
        self.controls.append(ComplexityControlFact(
            kind=kind, line=line, column=column,
            parent_index=self.parents[-1] if self.parents else None,
            **cardinality,
        ))
        self.parents.append(index)
        self.generic_visit(node)
        self.parents.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return

    def visit_If(self, node: ast.If) -> None:
        self._control(node, "if")

    def visit_For(self, node: ast.For) -> None:
        self._control(node, "for")

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self._control(node, "async_for")

    def visit_While(self, node: ast.While) -> None:
        self._control(node, "while")

    def visit_Try(self, node: ast.Try) -> None:
        self._control(node, "try")

    def visit_TryStar(self, node: ast.TryStar) -> None:
        self._control(node, "try_star")

    def visit_Match(self, node: ast.Match) -> None:
        self._control(node, "match", case_count=len(node.cases))

    def visit_IfExp(self, node: ast.IfExp) -> None:
        self._control(node, "if_expression")

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        self.controls.append(ComplexityControlFact(
            "boolean", node.lineno, node.col_offset,
            self.parents[-1] if self.parents else None, operand_count=len(node.values),
        ))
        self.generic_visit(node)

    def visit_comprehension(self, node: ast.comprehension) -> None:
        self._control(node, "comprehension", filter_count=len(node.ifs))

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        expression = "bare except" if node.type is None else ast.unparse(node.type)
        self.controls.append(ComplexityControlFact(
            "exception_handler", node.lineno, node.col_offset,
            self.parents[-1] if self.parents else None, expression=expression,
        ))
        if node.type is None:
            pass
        self.generic_visit(node)

    def visit_Return(self, node: ast.Return) -> None:
        self._occurrence("return", node)
        self.generic_visit(node)

    def visit_Raise(self, node: ast.Raise) -> None:
        expression = None
        if node.exc is not None:
            target = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
            expression = ast.unparse(target)
        self._occurrence("raise", node, expression)
        self.generic_visit(node)

    def visit_Await(self, node: ast.Await) -> None:
        self._occurrence("await", node)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if isinstance(node.value, ast.Name) and node.value.id == "self":
            self._occurrence("self_attribute", node, node.attr)
        self.generic_visit(node)


def collect_complexity_facts(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> FunctionComplexityFacts:
    visitor = _FactsVisitor()
    for statement in node.body:
        visitor.visit(statement)
    end_line = getattr(node, "end_lineno", None) or node.lineno
    end_column = getattr(node, "end_col_offset", None)
    if end_column is None:
        end_column = node.col_offset
    return FunctionComplexityFacts(
        node.lineno, node.col_offset, end_line, end_column,
        isinstance(node, ast.AsyncFunctionDef), visitor.controls, visitor.occurrences,
    )


def project_legacy_metrics(facts: FunctionComplexityFacts) -> FunctionMetricsInfo:
    """Compatibility projection; formulas intentionally match the old visitor."""
    cyclomatic, cognitive, maximum = 1, 0, 0
    depths: list[int] = []
    for control in facts.controls:
        depth = depths[control.parent_index] + 1 if control.parent_index is not None else 0
        depths.append(depth)
        if control.kind in {"try", "try_star"}:
            increment = 0
        elif control.kind == "match":
            increment = max(1, control.case_count - 1)
        elif control.kind == "boolean":
            increment = max(0, control.operand_count - 1)
        elif control.kind == "comprehension":
            increment = 1 + control.filter_count
        else:
            increment = 1
        cyclomatic += increment
        if control.kind == "boolean":
            cognitive += increment
        elif control.kind == "comprehension":
            cognitive += increment + depth
        else:
            cognitive += 1 + depth
        if control.kind not in {"boolean", "exception_handler"}:
            maximum = max(maximum, depth + 1)
    occurrences = facts.occurrences
    caught = {item.expression for item in facts.controls if item.kind == "exception_handler"}
    raised = {item.expression for item in occurrences if item.kind == "raise" and item.expression is not None}
    attributes = {item.expression for item in occurrences if item.kind == "self_attribute"}
    return FunctionMetricsInfo(
        cyclomatic_complexity=cyclomatic, cognitive_complexity=cognitive,
        max_nesting=maximum, lines_of_code=max(1, facts.end_line - facts.start_line + 1),
        statement_count=sum(item.kind == "statement" for item in occurrences),
        return_count=sum(item.kind == "return" for item in occurrences),
        raise_count=sum(item.kind == "raise" for item in occurrences),
        await_count=sum(item.kind == "await" for item in occurrences),
        broad_exception_handlers=sum(
            item.kind == "exception_handler"
            and item.expression in {"bare except", "Exception", "BaseException"}
            for item in facts.controls
        ),
        raised_exceptions=sorted(raised), caught_exceptions=sorted(caught),
        self_attribute_accesses=sorted(attributes), is_async=facts.is_async,
    )


def analyze_function_metrics(node: ast.FunctionDef | ast.AsyncFunctionDef) -> FunctionMetricsInfo:
    return project_legacy_metrics(collect_complexity_facts(node))
