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


class _CallableBindingVisitor(ast.NodeVisitor):
    """Collect names made local by Python's callable-scope rules."""

    def __init__(self) -> None:
        self.bindings: set[str] = set()
        self.declared_external: set[str] = set()
        self.global_bindings: set[str] = set()

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.bindings.add(node.id)

    def visit_Global(self, node: ast.Global) -> None:
        self.declared_external.update(node.names)
        self.global_bindings.update(node.names)

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        self.declared_external.update(node.names)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.bindings.add(node.name)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.bindings.add(node.name)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.bindings.add(alias.asname or alias.name.split(".", 1)[0])

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            if alias.name != "*":
                self.bindings.add(alias.asname or alias.name)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name:
            self.bindings.add(node.name)
        for statement in node.body:
            self.visit(statement)

    def visit_MatchAs(self, node: ast.MatchAs) -> None:
        if node.name:
            self.bindings.add(node.name)
        if node.pattern:
            self.visit(node.pattern)

    def visit_MatchStar(self, node: ast.MatchStar) -> None:
        if node.name:
            self.bindings.add(node.name)

    def visit_MatchMapping(self, node: ast.MatchMapping) -> None:
        if node.rest:
            self.bindings.add(node.rest)
        self.generic_visit(node)

    def _visit_comprehension(self, node: ast.AST) -> None:
        for generator in node.generators:
            self.visit(generator.iter)
            for condition in generator.ifs:
                self.visit(condition)
        if isinstance(node, ast.DictComp):
            self.visit(node.key)
            self.visit(node.value)
        else:
            self.visit(node.elt)

    visit_ListComp = _visit_comprehension
    visit_SetComp = _visit_comprehension
    visit_GeneratorExp = _visit_comprehension
    visit_DictComp = _visit_comprehension


class _ExpressionBindingVisitor(ast.NodeVisitor):
    """Record comprehension-local bindings visible at each loaded name."""

    def __init__(self) -> None:
        self.active: list[set[str]] = []
        self.bindings: dict[int, frozenset[str]] = {}

    @staticmethod
    def _target_names(target: ast.AST) -> set[str]:
        return {
            item.id
            for item in ast.walk(target)
            if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Store)
        }

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load) and self.active:
            names = set().union(*self.active)
            if names:
                self.bindings[id(node)] = frozenset(names)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    visit_AsyncFunctionDef = visit_FunctionDef
    visit_ClassDef = visit_FunctionDef
    visit_Lambda = visit_FunctionDef

    def _visit_comprehension(self, node: ast.AST) -> None:
        local: set[str] = set()
        self.active.append(local)
        for generator in node.generators:
            self.visit(generator.iter)
            local.update(self._target_names(generator.target))
            for condition in generator.ifs:
                self.visit(condition)
        if isinstance(node, ast.DictComp):
            self.visit(node.key)
            self.visit(node.value)
        else:
            self.visit(node.elt)
        self.active.pop()

    visit_ListComp = _visit_comprehension
    visit_SetComp = _visit_comprehension
    visit_GeneratorExp = _visit_comprehension
    visit_DictComp = _visit_comprehension


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
        self.semantic_modules = {module.module for module in modules}

    @staticmethod
    def _root_name(node: ast.expr) -> ast.Name | None:
        while isinstance(node, ast.Attribute):
            node = node.value
        return node if isinstance(node, ast.Name) else None

    def _exact_member(self, module: str, member: str) -> str | None:
        if (module, member) in self.classes_by_module:
            return f"{member}.__init__"
        if (module, member) in self.functions_by_module:
            return member
        class_name, separator, method_name = member.partition(".")
        class_info = self.classes_by_module.get((module, class_name))
        if separator and class_info and any(
            method.name == method_name for method in class_info.methods
        ):
            return member
        return None

    @staticmethod
    def _prepare_expression_bindings(body: Iterable[ast.stmt], scope: Scope) -> None:
        visitor = _ExpressionBindingVisitor()
        for statement in body:
            visitor.visit(statement)
        scope.expression_bindings.update(visitor.bindings)

    def resolve_all(self) -> None:
        for module in self.modules:
            module_scope = Scope()
            self._prepare_expression_bindings(module.tree.body, module_scope)
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
        assert function.node is not None
        arguments = function.node.args
        parameter_names = {
            argument.arg
            for argument in (
                *arguments.posonlyargs,
                *arguments.args,
                *arguments.kwonlyargs,
            )
        }
        if arguments.vararg:
            parameter_names.add(arguments.vararg.arg)
        if arguments.kwarg:
            parameter_names.add(arguments.kwarg.arg)
        binding_visitor = _CallableBindingVisitor()
        for statement in function.node.body:
            binding_visitor.visit(statement)
        scope.lexical_bindings.update(
            (parameter_names | binding_visitor.bindings)
            - binding_visitor.declared_external
        )
        self._prepare_expression_bindings(function.node.body, scope)
        for argument in function.args:
            if isinstance(argument.annotation, str):
                scope.bind_type(argument.name.lstrip("*"), argument.annotation)
        for name, annotation in (fields or {}).items():
            scope.bind_type(f"self.{name}", annotation)
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
            self._bind_statement(statement, module, scope, owner)
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

    def _bind_statement(
        self, statement: ast.stmt, module: ModuleInfo, scope: Scope, owner: str | None
    ) -> None:
        if isinstance(statement, (ast.Import, ast.ImportFrom)):
            imports = {
                item.local_name: item
                for item in module.imports
                if item.line == statement.lineno
            }
            for name, imported in imports.items():
                scope.bind_import(name, imported)
            return
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            scope.bind_name(statement.name)
            return
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        annotation: ast.expr | None = None
        if isinstance(statement, ast.Assign):
            targets, value = statement.targets, statement.value
        elif isinstance(statement, ast.AnnAssign):
            targets, value, annotation = [statement.target], statement.value, statement.annotation
        elif isinstance(statement, (ast.For, ast.AsyncFor)):
            targets = [statement.target]
        for target in targets:
            for item in ast.walk(target):
                if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Store):
                    scope.bind_name(item.id)
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
            imported = (
                None
                if scope.shadows_import(name, target)
                else scope.import_for(name)
            )
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
            root, *attributes = syntax.split(".")
            root_node = self._root_name(target)
            imported = (
                None
                if scope.shadows_import(root, root_node)
                else scope.import_for(root)
            )
            if imported and imported.local_module:
                if imported.module == "" and not imported.asname:
                    # A plain dotted import binds only its first component.  Do
                    # not discard the remaining source attribute path.
                    semantic = syntax
                else:
                    semantic = ".".join([imported.local_module, *attributes])
                parts = semantic.split(".")
                # Resolve against exact project module names, longest first;
                # this also obeys ProjectIndex's package-over-module choice.
                for boundary in range(len(parts) - 1, 0, -1):
                    target_module = ".".join(parts[:boundary])
                    member = ".".join(parts[boundary:])
                    if target_module not in self.semantic_modules:
                        continue
                    if (target_module, member) in self.classes_by_module:
                        return f"{member}.__init__"
                    if (target_module, member) in self.functions_by_module:
                        return member
            if isinstance(target.value, ast.Name):
                imported_module = (
                    None
                    if scope.shadows_import(target.value.id, target.value)
                    else scope.import_for(target.value.id)
                )
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

    def import_target(
        self, target: ast.expr, module: ModuleInfo, scope: Scope
    ) -> tuple[str, str] | None:
        """Return an exact, unshadowed project-local import target."""
        root_node = self._root_name(target)
        if root_node is None or scope.shadows_import(root_node.id, root_node):
            return None
        imported = scope.import_for(root_node.id)
        if not imported or not imported.local_module:
            return None
        if isinstance(target, ast.Name):
            if not imported.module:
                return None
            member = self._exact_member(imported.local_module, imported.object_name)
            if member is not None:
                return imported.local_module, member
            return None
        if not isinstance(target, ast.Attribute):
            return None

        syntax = dotted_name(target)
        _, *attributes = syntax.split(".")
        if imported.module and (
            imported.local_module,
            imported.object_name,
        ) in self.classes_by_module:
            semantic = ".".join(
                [imported.local_module, imported.object_name, *attributes]
            )
        elif imported.module == "" and not imported.asname:
            semantic = syntax
        else:
            semantic = ".".join([imported.local_module, *attributes])
        parts = semantic.split(".")
        for boundary in range(len(parts) - 1, 0, -1):
            target_module = ".".join(parts[:boundary])
            member = ".".join(parts[boundary:])
            exact_member = self._exact_member(target_module, member)
            if exact_member is not None:
                return target_module, exact_member
        return None

    def expression_value(
        self, node: ast.expr, module: ModuleInfo, scope: Scope, owner: str | None
    ) -> Any:
        if isinstance(node, ast.Call):
            nested = self.call_info(node, module, scope, owner)
            value = {
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
            if nested.semantic_target:
                value["semantic_target"] = {
                    "module": nested.semantic_target[0],
                    "object": nested.semantic_target[1],
                }
            return value
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Attribute):
            syntax = dotted_name(node)
            root = syntax.split(".", 1)[0]
            # Imported symbolic values (typically enum members) carry an
            # explicit value marker. Attributes of parameters and locals stay
            # as source expressions, matching the established graph contract.
            root_node = self._root_name(node)
            if (
                scope.import_for(root) is not None
                and not scope.shadows_import(root, root_node)
            ):
                imported = scope.import_for(root)
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
            semantic_target=self.import_target(node.func, module, scope),
            args=arguments,
            file=module.file,
            line=node.lineno,
            column=node.col_offset,
        )
