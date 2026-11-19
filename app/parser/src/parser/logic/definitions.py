"""Definition collection from one already-parsed AST module."""

from __future__ import annotations

import ast
from collections.abc import Callable, Iterable

from .complexity import collect_complexity_facts, project_legacy_metrics
from .expressions import annotation_value, dotted_name, infer_literal_type, simple_value
from .models import ArgumentInfo, ClassInfo, FieldInfo, FunctionInfo, ModuleInfo


def _decorators(node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    return [dotted_name(item) for item in node.decorator_list]


def _function_args(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ArgumentInfo]:
    arguments = node.args
    positional = [*arguments.posonlyargs, *arguments.args]
    defaults: list[ast.expr | None] = [None] * (len(positional) - len(arguments.defaults))
    defaults.extend(arguments.defaults)
    result: list[ArgumentInfo] = []
    for item, default in zip(positional, defaults):
        if item.arg in {"self", "cls"}:
            continue
        result.append(
            ArgumentInfo(
                name=item.arg,
                annotation=annotation_value(item.annotation),
                default=simple_value(default),
                line=item.lineno,
                column=item.col_offset,
            )
        )
    if arguments.vararg:
        result.append(
            ArgumentInfo(
                name=f"*{arguments.vararg.arg}",
                annotation=annotation_value(arguments.vararg.annotation),
            )
        )
    for item, default in zip(arguments.kwonlyargs, arguments.kw_defaults):
        result.append(
            ArgumentInfo(
                name=item.arg,
                annotation=annotation_value(item.annotation),
                default=simple_value(default),
                line=item.lineno,
                column=item.col_offset,
            )
        )
    if arguments.kwarg:
        result.append(
            ArgumentInfo(
                name=f"**{arguments.kwarg.arg}",
                annotation=annotation_value(arguments.kwarg.annotation),
            )
        )
    return result


def _function(
    node: ast.FunctionDef | ast.AsyncFunctionDef, module: ModuleInfo, owner: str | None
) -> FunctionInfo:
    facts = collect_complexity_facts(node)
    return FunctionInfo(
        name=node.name,
        args=_function_args(node),
        # The public contract keeps function return annotations verbatim while
        # field generics use the compact parent/child representation.
        return_type=ast.unparse(node.returns) if node.returns is not None else None,
        decorators=_decorators(node),
        metrics=project_legacy_metrics(facts),
        complexity_facts=facts,
        node=node,
        owner=owner,
        file=module.file,
        line=node.lineno,
        column=node.col_offset,
    )


def _class_fields(node: ast.ClassDef, module: ModuleInfo) -> list[FieldInfo]:
    fields: list[FieldInfo] = []
    seen: set[str] = set()

    def append(field: FieldInfo) -> None:
        if field.name not in seen:
            seen.add(field.name)
            fields.append(field)

    for statement in node.body:
        if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
            append(
                FieldInfo(
                    name=statement.target.id,
                    annotation=annotation_value(statement.annotation),
                    value=simple_value(statement.value),
                    value_node=statement.value,
                    annotation_node=statement.annotation,
                    annotation_source=ast.unparse(statement.annotation),
                    file=module.file,
                    line=statement.lineno,
                    column=statement.col_offset,
                )
            )
        elif isinstance(statement, (ast.Assign, ast.AnnAssign)):
            targets: Iterable[ast.expr]
            value: ast.expr | None
            if isinstance(statement, ast.Assign):
                targets, value = statement.targets, statement.value
            else:
                targets, value = [statement.target], statement.value
            for target in targets:
                if isinstance(target, ast.Name):
                    append(
                        FieldInfo(
                            name=target.id,
                            annotation=infer_literal_type(value),
                            value=simple_value(value),
                            value_node=value,
                            file=module.file,
                            line=statement.lineno,
                            column=statement.col_offset,
                        )
                    )

    init = next(
        (
            statement
            for statement in node.body
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
            and statement.name == "__init__"
        ),
        None,
    )
    if init:
        class ConstructorStatementVisitor(ast.NodeVisitor):
            def __init__(self) -> None:
                self.statements: list[ast.Assign | ast.AnnAssign] = []

            def visit_Assign(self, statement: ast.Assign) -> None:
                self.statements.append(statement)
                self.generic_visit(statement)

            def visit_AnnAssign(self, statement: ast.AnnAssign) -> None:
                self.statements.append(statement)
                self.generic_visit(statement)

            def _skip_scope(self, scope: ast.AST) -> None:
                return

            visit_FunctionDef = _skip_scope
            visit_AsyncFunctionDef = _skip_scope
            visit_ClassDef = _skip_scope
            visit_Lambda = _skip_scope
            visit_ListComp = _skip_scope
            visit_SetComp = _skip_scope
            visit_DictComp = _skip_scope
            visit_GeneratorExp = _skip_scope

        visitor = ConstructorStatementVisitor()
        for constructor_statement in init.body:
            visitor.visit(constructor_statement)
        for statement in visitor.statements:
            target: ast.expr | None = None
            annotation = None
            value = None
            if isinstance(statement, ast.AnnAssign):
                target, annotation, value = (
                    statement.target,
                    annotation_value(statement.annotation),
                    statement.value,
                )
            elif isinstance(statement, ast.Assign) and len(statement.targets) == 1:
                target, value = statement.targets[0], statement.value
            if (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "self"
            ):
                append(
                    FieldInfo(
                        name=target.attr,
                        annotation=annotation or _called_name(value),
                        value=simple_value(value),
                        value_node=value,
                        annotation_node=(statement.annotation if isinstance(statement, ast.AnnAssign) else None),
                        annotation_source=(ast.unparse(statement.annotation) if isinstance(statement, ast.AnnAssign) else None),
                        file=module.file,
                        line=statement.lineno,
                        column=statement.col_offset,
                    )
                )
    return fields


def _called_name(node: ast.expr | None) -> str | None:
    return dotted_name(node.func) if isinstance(node, ast.Call) else infer_literal_type(node)


def _module_constant(
    node: ast.Assign | ast.AnnAssign, module: ModuleInfo
) -> list[FieldInfo]:
    """Collect literal assignments declared directly in a module."""
    if isinstance(node, ast.Assign):
        targets = node.targets
        value = node.value
        annotation = infer_literal_type(value)
    else:
        targets = [node.target]
        value = node.value
        annotation = annotation_value(node.annotation)
    literal_nodes = (ast.Constant, ast.List, ast.Tuple, ast.Dict, ast.Set, ast.UnaryOp)
    if value is not None and not isinstance(value, literal_nodes):
        return []
    return [
        FieldInfo(
            name=target.id,
            annotation=annotation,
            value=simple_value(value),
            value_node=value,
            file=module.file,
            line=node.lineno,
            column=node.col_offset,
        )
        for target in targets
        if isinstance(target, ast.Name)
    ]


def collect_definitions(
    module: ModuleInfo, on_node: Callable[[ast.stmt], None] | None = None
) -> None:
    for node in module.tree.body:
        if on_node is not None:
            on_node(node)
        if isinstance(node, ast.ClassDef):
            info = ClassInfo(
                name=node.name,
                parents=[dotted_name(item) for item in node.bases],
                parent_nodes=list(node.bases),
                fields=_class_fields(node, module),
                decorators=_decorators(node),
                node=node,
                module=module.module,
                file=module.file,
                line=node.lineno,
                column=node.col_offset,
            )
            info.methods = [
                _function(item, module, owner=node.name)
                for item in node.body
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            info.abstract_methods = {
                method.name
                for method in info.methods
                if any(name.rsplit(".", 1)[-1] == "abstractmethod" for name in method.decorators)
            }
            module.classes.append(info)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            module.functions.append(_function(node, module, owner=None))
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            module.constants.extend(_module_constant(node, module))
