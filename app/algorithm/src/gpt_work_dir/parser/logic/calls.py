"""Callsite collection and conservative target resolution."""

from __future__ import annotations

import ast
from collections.abc import Iterable
from typing import Any

from .expressions import dotted_name
from .models import CallArgumentInfo, CallInfo, FunctionInfo, ModuleInfo
from .scope import Scope


class _OutermostCallVisitor(ast.NodeVisitor):
    """Collect calls represented at this level; nested calls live in arguments."""

    def __init__(self) -> None:
        self.calls: list[ast.Call] = []

    def visit_Call(self, node: ast.Call) -> None:
        self.calls.append(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return


class CallResolver:
    def __init__(self, modules: list[ModuleInfo]) -> None:
        self.modules = modules
        self.classes_by_module = {
            (module.module, item.name): item
            for module in modules
            for item in module.classes
        }
        self.functions_by_module = {
            (module.module, item.name): item
            for module in modules
            for item in module.functions
        }

    def resolve_all(self) -> None:
        for module in self.modules:
            module_scope = Scope()
            module.calls = self._analyze_body(
                module.tree.body, module, module_scope, owner=None
            )
            for function in module.functions:
                function.calls = self._analyze_function(function, module, module_scope)
            for class_info in module.classes:
                for method in class_info.methods:
                    method.calls = self._analyze_function(
                        method,
                        module,
                        module_scope,
                        owner=class_info.name,
                        fields={
                            field.name: field.annotation
                            for field in class_info.fields
                            if isinstance(field.annotation, str)
                        },
                    )

    def _analyze_function(
        self,
        function: FunctionInfo,
        module: ModuleInfo,
        parent: Scope,
        owner: str | None = None,
        fields: dict[str, str] | None = None,
    ) -> list[CallInfo]:
        scope = Scope(parent=parent, owner_class=owner)
        for argument in function.args:
            if isinstance(argument.annotation, str):
                scope.bind_type(argument.name.lstrip("*"), argument.annotation)
        for name, annotation in (fields or {}).items():
            scope.bind_type(f"self.{name}", annotation)
        assert function.node is not None
        return self._analyze_body(function.node.body, module, scope, owner)

    def _analyze_body(
        self,
        body: Iterable[ast.stmt],
        module: ModuleInfo,
        scope: Scope,
        owner: str | None,
    ) -> list[CallInfo]:
        result: list[CallInfo] = []
        for statement in body:
            result.extend(self._calls_in_statement(statement, module, scope, owner))
            self._bind_assignment(statement, module, scope, owner)
            for nested in self._nested_bodies(statement):
                result.extend(self._analyze_body(nested, module, scope, owner))
        return result

    def _calls_in_statement(
        self, statement: ast.stmt, module: ModuleInfo, scope: Scope, owner: str | None
    ) -> list[CallInfo]:
        visitor = _OutermostCallVisitor()
        for _, value in ast.iter_fields(statement):
            if isinstance(value, ast.expr):
                visitor.visit(value)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, ast.expr):
                        visitor.visit(item)
        return [self.call_info(node, module, scope, owner) for node in visitor.calls]

    @staticmethod
    def _nested_bodies(statement: ast.stmt) -> list[list[ast.stmt]]:
        result: list[list[ast.stmt]] = []
        for field_name in ("body", "orelse", "finalbody"):
            value = getattr(statement, field_name, None)
            if isinstance(value, list) and value and all(isinstance(item, ast.stmt) for item in value):
                # Definitions own independent scopes and are analyzed separately.
                if not isinstance(
                    statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                ):
                    result.append(value)
        if isinstance(statement, ast.Try):
            result.extend(handler.body for handler in statement.handlers)
        if isinstance(statement, ast.Match):
            result.extend(case.body for case in statement.cases)
        return result

    def _bind_assignment(
        self, statement: ast.stmt, module: ModuleInfo, scope: Scope, owner: str | None
    ) -> None:
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        annotation: ast.expr | None = None
        if isinstance(statement, ast.Assign):
            targets, value = statement.targets, statement.value
        elif isinstance(statement, ast.AnnAssign):
            targets, value, annotation = [statement.target], statement.value, statement.annotation
        elif isinstance(statement, (ast.For, ast.AsyncFor)):
            targets = [statement.target]
        type_name: str | None = ast.unparse(annotation) if annotation is not None else None
        if type_name is None and isinstance(value, ast.Call):
            resolved = self.resolve_target(value.func, module, scope, owner)
            if resolved.endswith(".__init__"):
                type_name = resolved[: -len(".__init__")]
        if type_name:
            for target in targets:
                if isinstance(target, (ast.Name, ast.Attribute)):
                    scope.bind_type(dotted_name(target), type_name)

    def resolve_target(
        self, target: ast.expr, module: ModuleInfo, scope: Scope, owner: str | None
    ) -> str:
        if isinstance(target, ast.Name):
            name = target.id
            imported = module.import_aliases.get(name)
            if imported:
                original = imported.object_name
                if imported.local_module and (
                    imported.local_module,
                    original,
                ) in self.classes_by_module:
                    return f"{original}.__init__"
                return original
            if (module.module, name) in self.classes_by_module:
                return f"{name}.__init__"
            return name
        if isinstance(target, ast.Attribute):
            syntax = dotted_name(target)
            base = dotted_name(target.value)
            inferred = scope.type_of(base)
            if inferred:
                return f"{inferred}.{target.attr}"
            if isinstance(target.value, ast.Name):
                imported_module = module.import_aliases.get(target.value.id)
                if imported_module and imported_module.local_module:
                    imported_name = imported_module.local_module
                    if (imported_name, target.attr) in self.classes_by_module:
                        return f"{target.attr}.__init__"
                    if (imported_name, target.attr) in self.functions_by_module:
                        return target.attr
                inferred = scope.type_of(target.value.id)
                if inferred:
                    return f"{inferred}.{target.attr}"
                if target.value.id == "self" and owner:
                    class_info = self.classes_by_module.get((module.module, owner))
                    if class_info and any(item.name == target.attr for item in class_info.methods):
                        return f"{owner}.{target.attr}"
            return syntax
        return ast.unparse(target)

    def expression_value(
        self, node: ast.expr, module: ModuleInfo, scope: Scope, owner: str | None
    ) -> Any:
        if isinstance(node, ast.Call):
            nested = self.call_info(node, module, scope, owner)
            return {
                "type": "call",
                "object": nested.object_name,
                "args": [
                    {
                        "name": argument.name,
                        "value": argument.value,
                    }
                    for argument in nested.args
                ],
            }
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Attribute):
            syntax = dotted_name(node)
            root = syntax.split(".", 1)[0]
            # Imported symbolic values (typically enum members) carry an
            # explicit value marker. Attributes of parameters and locals stay
            # as source expressions, matching the established graph contract.
            if root in module.import_aliases:
                imported = module.import_aliases[root]
                original = imported.object_name
                suffix = syntax[len(root) :]
                return {"type": "value", "object": f"{original}{suffix}"}
            return syntax
        if isinstance(node, ast.UnaryOp) and isinstance(node.operand, ast.Constant):
            try:
                return ast.literal_eval(node)
            except (ValueError, TypeError):
                pass
        return ast.unparse(node)

    def call_info(
        self, node: ast.Call, module: ModuleInfo, scope: Scope, owner: str | None
    ) -> CallInfo:
        raw_arguments = [("", item) for item in node.args]
        raw_arguments.extend(
            (item.arg or "**", item.value) for item in node.keywords
        )
        arguments = [
            CallArgumentInfo(
                name,
                value_node,
                self.expression_value(value_node, module, scope, owner),
            )
            for name, value_node in raw_arguments
        ]
        return CallInfo(
            node=node,
            object_name=self.resolve_target(node.func, module, scope, owner),
            args=arguments,
            file=module.file,
            line=node.lineno,
            column=node.col_offset,
        )
