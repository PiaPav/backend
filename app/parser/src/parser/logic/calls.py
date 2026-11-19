"""Callsite collection and conservative target resolution."""

from __future__ import annotations

import ast
from collections.abc import Iterable
from typing import Any

from .expressions import dotted_name
from .imports import resolve_import_statement
from .models import (
    CanonicalCallsiteInfo,
    CallArgumentInfo,
    CallInfo,
    ClassInfo,
    FunctionInfo,
    ImportInfo,
    ModuleInfo,
)
from .project_index import ProjectIndex
from .scope import Scope


class _OutermostCallVisitor(ast.NodeVisitor):
    """Collect calls represented at this level; nested calls live in arguments."""

    def __init__(self) -> None:
        self.calls: list[ast.Call] = []

    def visit_Call(self, node: ast.Call) -> None:
        self.calls.append(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return


class _CanonicalCallVisitor(ast.NodeVisitor):
    """Collect every call while retaining call nesting and direct await state."""

    def __init__(self, scope: Scope) -> None:
        self.calls: list[tuple[ast.Call, int, bool, Scope]] = []
        self.depth = 0
        self.awaited_call: ast.Call | None = None
        self.scope = scope

    def visit_Await(self, node: ast.Await) -> None:
        previous = self.awaited_call
        self.awaited_call = node.value if isinstance(node.value, ast.Call) else None
        self.visit(node.value)
        self.awaited_call = previous

    def visit_Call(self, node: ast.Call) -> None:
        self.calls.append((node, self.depth, node is self.awaited_call, self.scope.fork()))
        previous_awaited = self.awaited_call
        self.awaited_call = None
        self.depth += 1
        self.generic_visit(node)
        self.depth -= 1
        self.awaited_call = previous_awaited

    def visit_Lambda(self, node: ast.Lambda) -> None:
        for default in node.args.defaults:
            self.visit(default)
        for default in node.args.kw_defaults:
            if default is not None:
                self.visit(default)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        # Assignment expressions bind only after their value has been evaluated.
        self.visit(node.value)
        CallResolver._bind_targets(self.scope, [node.target])


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


TargetRef = tuple[str, int]


class CallResolver:
    def __init__(self, modules: list[ModuleInfo], index: ProjectIndex) -> None:
        self.modules = modules
        self.index = index
        # Legacy string resolution remains unchanged for the transitional body.
        self.classes_by_module = {
            (module.module, item.name): item for module in modules for item in module.classes
        }
        self.functions_by_module = {
            (module.module, item.name): item for module in modules for item in module.functions
        }
        self.definitions_by_node = {
            id(item.node): item
            for module in modules
            for item in (
                *module.functions,
                *module.classes,
                *(method for class_info in module.classes for method in class_info.methods),
            )
            if item.node is not None
        }
        self.effective_modules = index.by_module
        self.semantic_modules = {module.module for module in modules}

    @staticmethod
    def _function_ref(function: FunctionInfo) -> TargetRef:
        return ("method" if function.owner else "function", id(function))

    @staticmethod
    def _class_ref(class_info: ClassInfo) -> TargetRef:
        return "class", id(class_info)

    @staticmethod
    def _constructor_ref(class_info: ClassInfo) -> TargetRef:
        init = next((item for item in reversed(class_info.methods) if item.name == "__init__"), None)
        return ("method", id(init)) if init is not None else ("constructor", id(class_info))

    @staticmethod
    def _bound_class(module: ModuleInfo, name: str) -> ClassInfo | None:
        return next((item for item in reversed(module.classes) if item.name == name), None)

    @staticmethod
    def _bound_function(module: ModuleInfo, name: str) -> FunctionInfo | None:
        return next((item for item in reversed(module.functions) if item.name == name), None)

    @staticmethod
    def _root_name(node: ast.expr) -> ast.Name | None:
        while isinstance(node, ast.Attribute):
            node = node.value
        return node if isinstance(node, ast.Name) else None

    def _exact_member_ref(self, module_name: str, member: str) -> TargetRef | None:
        module = self.effective_modules.get(module_name)
        if module is None:
            return None
        class_info = self._bound_class(module, member)
        if class_info is not None:
            return self._constructor_ref(class_info)
        function = self._bound_function(module, member)
        if function is not None:
            return self._function_ref(function)
        class_name, separator, method_name = member.partition(".")
        class_info = self._bound_class(module, class_name)
        method = next(
            (item for item in reversed(class_info.methods) if item.name == method_name),
            None,
        ) if separator and class_info else None
        if method is not None:
            return self._function_ref(method)
        return None

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
            legacy_scope = Scope()
            self._prepare_expression_bindings(module.tree.body, legacy_scope)
            module.calls = self._analyze_body(
                module.tree.body, module, legacy_scope, owner=None,
            )
            canonical_scope = Scope()
            self._prepare_expression_bindings(module.tree.body, canonical_scope)
            self._analyze_body(
                module.tree.body, module, canonical_scope, owner=None,
                canonical=module.canonical_callsites, collect_legacy=False,
            )
            for function in module.functions:
                function.calls = self._analyze_function(
                    function, module, legacy_scope, canonical_scope
                )
            for class_info in module.classes:
                for method in class_info.methods:
                    method.calls = self._analyze_function(
                        method,
                        module,
                        legacy_scope,
                        canonical_scope,
                        owner=class_info,
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
        legacy_parent: Scope,
        canonical_parent: Scope,
        owner: ClassInfo | None = None,
        fields: dict[str, str] | None = None,
    ) -> list[CallInfo]:
        def make_scope(parent: Scope, *, canonical: bool = False) -> Scope:
            scope = Scope(parent=parent, owner_class=owner)
            scope.lexical_bindings.update(
                (parameter_names | binding_visitor.bindings)
                - binding_visitor.declared_external
            )
            if canonical:
                type_parameters = self._type_parameter_names(function.node)
                if owner is not None and owner.node is not None:
                    type_parameters.update(self._type_parameter_names(owner.node))
                scope.lexical_bindings.update(type_parameters)
                scope.canonical_type_parameters.update(type_parameters)
            self._prepare_expression_bindings(function.node.body, scope)
            for argument in function.args:
                if isinstance(argument.annotation, str):
                    argument_name = argument.name.lstrip("*")
                    scope.bind_type(argument_name, argument.annotation)
                    class_target = self._class_target_for_type(argument.annotation, module, scope)
                    if class_target is not None:
                        scope.bind_canonical_type(argument_name, class_target)
            for name, annotation in (fields or {}).items():
                scope.bind_type(f"self.{name}", annotation)
            return scope

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
        legacy_scope = make_scope(legacy_parent)
        calls = self._analyze_body(
            function.node.body,
            module,
            legacy_scope,
            owner,
        )
        canonical_scope = make_scope(canonical_parent, canonical=True)
        self._analyze_body(
            function.node.body, module, canonical_scope, owner,
            canonical=function.canonical_callsites, collect_legacy=False,
        )
        return calls

    def _class_target_for_type(
        self, type_name: str, module: ModuleInfo, scope: Scope
    ) -> TargetRef | None:
        root = type_name.strip("'\"").split("[", 1)[0].split(".", 1)[0]
        if scope.is_canonical_type_parameter(root):
            return None
        local_matches = [item for item in module.classes if item.name == type_name]
        if len(local_matches) == 1:
            return self._class_ref(local_matches[0])
        imported = scope.canonical_import_for(type_name)
        if imported and imported.local_module:
            imported_module = self.effective_modules.get(imported.local_module)
            candidate = self._bound_class(imported_module, imported.object_name) if imported_module else None
            if candidate is not None:
                return self._class_ref(candidate)
        return None

    def _analyze_body(
        self,
        body: Iterable[ast.stmt],
        module: ModuleInfo,
        scope: Scope,
        owner: ClassInfo | None,
        canonical: list[CanonicalCallsiteInfo] | None = None,
        collect_legacy: bool = True,
    ) -> list[CallInfo]:
        result: list[CallInfo] = []
        for statement in body:
            if canonical is not None:
                canonical.extend(self._canonical_calls_in_statement(statement, module, scope, owner))
            if collect_legacy:
                result.extend(self._calls_in_statement(statement, module, scope, owner))
            if canonical is None:
                self._bind_statement(statement, module, scope, owner)
                for nested in self._nested_bodies(statement):
                    result.extend(self._analyze_body(nested, module, scope, owner))
                continue
            if isinstance(statement, ast.If):
                branches = [scope.fork(), scope.fork()]
                result.extend(self._analyze_body(statement.body, module, branches[0], owner, canonical, collect_legacy))
                if statement.orelse:
                    result.extend(self._analyze_body(statement.orelse, module, branches[1], owner, canonical, collect_legacy))
                scope.merge_flows(branches)
                continue
            if isinstance(statement, (ast.For, ast.AsyncFor, ast.While)):
                zero_iteration = scope.fork()
                iteration = scope.fork()
                rebound = _CallableBindingVisitor()
                for body_statement in statement.body:
                    rebound.visit(body_statement)
                self._bind_targets(iteration, rebound.bindings)
                if isinstance(statement, (ast.For, ast.AsyncFor)):
                    self._bind_targets(iteration, [statement.target])
                result.extend(self._analyze_body(
                    statement.body, module, iteration, owner, canonical, collect_legacy
                ))
                loop_exit = scope.fork()
                loop_exit.merge_flows([zero_iteration, iteration])
                if statement.orelse:
                    after_else = loop_exit.fork()
                    result.extend(self._analyze_body(
                        statement.orelse, module, after_else, owner, canonical, collect_legacy
                    ))
                    scope.merge_flows([loop_exit, after_else])
                else:
                    scope.merge_flows([zero_iteration, iteration])
                continue
            if isinstance(statement, (ast.With, ast.AsyncWith)):
                for item in statement.items:
                    canonical.extend(self._canonical_calls_in_expression(
                        item.context_expr, module, scope, owner
                    ))
                    self._bind_targets(scope, [item.optional_vars])
                result.extend(self._analyze_body(
                    statement.body, module, scope, owner, canonical, collect_legacy
                ))
                continue
            if isinstance(statement, (ast.Try, ast.TryStar)):
                branches: list[Scope] = []
                successful = scope.fork()
                result.extend(self._analyze_body(statement.body, module, successful, owner, canonical, collect_legacy))
                result.extend(self._analyze_body(statement.orelse, module, successful, owner, canonical, collect_legacy))
                branches.append(successful)
                possible_try_bindings = self._possible_binding_targets(statement.body)
                for handler in statement.handlers:
                    branch = scope.fork()
                    self._bind_targets(branch, possible_try_bindings)
                    if handler.type is not None:
                        canonical.extend(self._canonical_calls_in_expression(
                            handler.type, module, branch, owner
                        ))
                    self._bind_targets(branch, [handler.name])
                    result.extend(self._analyze_body(handler.body, module, branch, owner, canonical, collect_legacy))
                    branches.append(branch)
                scope.merge_flows(branches)
                result.extend(self._analyze_body(statement.finalbody, module, scope, owner, canonical, collect_legacy))
                continue
            if isinstance(statement, ast.Match):
                branches = [scope.fork()]
                for case in statement.cases:
                    branch = scope.fork()
                    self._bind_targets(branch, self._match_capture_names(case.pattern))
                    if canonical is not None and case.guard is not None:
                        canonical.extend(self._canonical_calls_in_expression(case.guard, module, branch, owner))
                    result.extend(self._analyze_body(case.body, module, branch, owner, canonical, collect_legacy))
                    branches.append(branch)
                scope.merge_flows(branches)
                continue
            if isinstance(statement, ast.ClassDef):
                class_scope = Scope(parent=scope)
                type_parameters = self._type_parameter_names(statement)
                class_scope.lexical_bindings.update(type_parameters)
                if canonical is not None:
                    class_scope.canonical_type_parameters.update(type_parameters)
                result.extend(self._analyze_body(
                    statement.body, module, class_scope, None, canonical, False
                ))
                self._bind_statement(statement, module, scope, owner)
            else:
                self._bind_statement(statement, module, scope, owner)
                for nested in self._nested_bodies(statement):
                    result.extend(self._analyze_body(nested, module, scope, owner, canonical, collect_legacy))
        return result

    def _calls_in_statement(
        self, statement: ast.stmt, module: ModuleInfo, scope: Scope, owner: ClassInfo | None
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

    def _canonical_calls_in_statement(
        self, statement: ast.stmt, module: ModuleInfo, scope: Scope, owner: ClassInfo | None
    ) -> list[CanonicalCallsiteInfo]:
        expressions: list[ast.expr] = []

        def collect(value: object) -> None:
            if isinstance(value, ast.expr):
                expressions.append(value)
            elif isinstance(value, ast.stmt):
                return
            elif isinstance(value, ast.AST):
                for _, child in ast.iter_fields(value):
                    collect(child)
            elif isinstance(value, list):
                for child in value:
                    collect(child)

        for _, value in ast.iter_fields(statement):
            collect(value)
        if isinstance(statement, ast.Match):
            guard_ids = {id(case.guard) for case in statement.cases if case.guard is not None}
            expressions = [item for item in expressions if id(item) not in guard_ids]
        if isinstance(statement, (ast.With, ast.AsyncWith)):
            context_ids = {id(item.context_expr) for item in statement.items}
            expressions = [item for item in expressions if id(item) not in context_ids]
        if isinstance(statement, (ast.Try, ast.TryStar)):
            type_ids = {id(handler.type) for handler in statement.handlers if handler.type is not None}
            expressions = [item for item in expressions if id(item) not in type_ids]
        type_parameter_names = self._type_parameter_names(statement)
        scoped_expressions: list[ast.expr] = []
        if type_parameter_names:
            for parameter in getattr(statement, "type_params", ()):
                bound = getattr(parameter, "bound", None)
                if bound is not None:
                    scoped_expressions.append(bound)
                default = getattr(parameter, "default_value", None)
                if default is not None:
                    scoped_expressions.append(default)
            if isinstance(statement, ast.ClassDef):
                scoped_expressions.extend(statement.bases)
                scoped_expressions.extend(keyword.value for keyword in statement.keywords)
            elif isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                arguments = statement.args
                parameters = [
                    *arguments.posonlyargs,
                    *arguments.args,
                    *arguments.kwonlyargs,
                ]
                if arguments.vararg is not None:
                    parameters.append(arguments.vararg)
                if arguments.kwarg is not None:
                    parameters.append(arguments.kwarg)
                scoped_expressions.extend(
                    parameter.annotation
                    for parameter in parameters
                    if parameter.annotation is not None
                )
                if statement.returns is not None:
                    scoped_expressions.append(statement.returns)

        scoped_ids = {id(expression) for expression in scoped_expressions}
        result = self._canonical_calls_in_expressions(
            (expression for expression in expressions if id(expression) not in scoped_ids),
            module,
            scope,
            owner,
        )
        if scoped_expressions:
            type_scope = scope.fork()
            for name in type_parameter_names:
                type_scope.bind_name(name)
            result.extend(self._canonical_calls_in_expressions(
                scoped_expressions, module, type_scope, owner
            ))
        return result

    @staticmethod
    def _type_parameter_names(node: ast.AST) -> set[str]:
        return {
            parameter.name
            for parameter in getattr(node, "type_params", ())
        }

    def _canonical_calls_in_expression(
        self, expression: ast.expr, module: ModuleInfo, scope: Scope,
        owner: ClassInfo | None,
    ) -> list[CanonicalCallsiteInfo]:
        return self._canonical_calls_in_expressions([expression], module, scope, owner)

    def _canonical_calls_in_expressions(
        self, expressions: Iterable[ast.expr], module: ModuleInfo, scope: Scope,
        owner: ClassInfo | None,
    ) -> list[CanonicalCallsiteInfo]:
        visitor = _CanonicalCallVisitor(scope)
        for expression in expressions:
            visitor.visit(expression)
        result: list[CanonicalCallsiteInfo] = []
        for node, depth, awaited, call_scope in visitor.calls:
            target = self.canonical_target(node.func, module, call_scope, owner)
            result.append(
                CanonicalCallsiteInfo(
                    node=node,
                    expression=ast.unparse(node),
                    syntactic_depth=depth,
                    awaited=awaited,
                    resolution=self._resolution(node.func, call_scope, target),
                    target=target,
                    file=module.file,
                    line=node.lineno,
                    column=node.col_offset,
                )
            )
        return result

    @staticmethod
    def _target_keys(target: ast.AST | str | None) -> list[str]:
        if isinstance(target, str):
            return [target]
        if target is None:
            return []
        if isinstance(target, ast.Name):
            return [target.id]
        if isinstance(target, ast.Attribute):
            dotted = dotted_name(target)
            return [dotted, dotted.split(".", 1)[0]]
        keys: list[str] = []
        for child in ast.iter_child_nodes(target):
            keys.extend(CallResolver._target_keys(child))
        return keys

    @classmethod
    def _bind_targets(cls, scope: Scope, targets: Iterable[ast.AST | str | None]) -> None:
        seen: set[str] = set()
        for target in targets:
            for key in cls._target_keys(target):
                if key not in seen:
                    scope.bind_name(key)
                    seen.add(key)

    @staticmethod
    def _match_capture_names(pattern: ast.pattern) -> list[str]:
        names: list[str] = []
        for item in ast.walk(pattern):
            if isinstance(item, (ast.MatchAs, ast.MatchStar)) and item.name:
                names.append(item.name)
            elif isinstance(item, ast.MatchMapping) and item.rest:
                names.append(item.rest)
        return names

    @classmethod
    def _possible_binding_targets(cls, body: Iterable[ast.stmt]) -> list[ast.AST | str]:
        targets: list[ast.AST | str] = []
        for statement in body:
            for item in ast.walk(statement):
                if isinstance(item, (ast.Name, ast.Attribute)) and isinstance(
                    item.ctx, (ast.Store, ast.Del)
                ):
                    targets.append(item)
                elif isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    targets.append(item.name)
                elif isinstance(item, ast.Import):
                    targets.extend(alias.asname or alias.name.split(".", 1)[0] for alias in item.names)
                elif isinstance(item, ast.ImportFrom):
                    targets.extend(alias.asname or alias.name for alias in item.names if alias.name != "*")
                elif isinstance(item, ast.ExceptHandler) and item.name:
                    targets.append(item.name)
                elif isinstance(item, (ast.MatchAs, ast.MatchStar)) and item.name:
                    targets.append(item.name)
                elif isinstance(item, ast.MatchMapping) and item.rest:
                    targets.append(item.rest)
        return targets

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
        self, statement: ast.stmt, module: ModuleInfo, scope: Scope, owner: ClassInfo | None
    ) -> None:
        if isinstance(statement, (ast.Import, ast.ImportFrom)):
            module_level = scope.parent is None
            imports = resolve_import_statement(statement, module, self.index)
            for imported in imports:
                name = imported.local_name
                if module_level:
                    scope.bind_import(name, imported)
                else:
                    scope.bind_canonical_import(name, imported)
            return
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            declaration = self.definitions_by_node.get(id(statement))
            if isinstance(declaration, ClassInfo):
                scope.bind_internal(statement.name, self._constructor_ref(declaration))
            elif isinstance(declaration, FunctionInfo):
                scope.bind_internal(statement.name, self._function_ref(declaration))
            else:
                scope.bind_name(statement.name)
            return
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        annotation: ast.expr | None = None
        if isinstance(statement, ast.Assign):
            targets, value = statement.targets, statement.value
        elif isinstance(statement, ast.AnnAssign):
            targets, value, annotation = [statement.target], statement.value, statement.annotation
        elif isinstance(statement, ast.AugAssign):
            targets, value = [statement.target], statement.value
        elif isinstance(statement, ast.Delete):
            targets = statement.targets
        elif isinstance(statement, (ast.For, ast.AsyncFor)):
            targets = [statement.target]
        self._bind_targets(scope, targets)
        type_name: str | None = ast.unparse(annotation) if annotation is not None else None
        if type_name is None and isinstance(value, ast.Call) and not isinstance(statement, ast.AugAssign):
            resolved = self.resolve_target(value.func, module, scope, owner)
            if resolved.endswith(".__init__"):
                type_name = resolved[: -len(".__init__")]
            canonical = self.canonical_target(value.func, module, scope, owner)
            class_target = self._class_ref_for_constructor(canonical)
            if class_target is not None:
                for target in targets:
                    if isinstance(target, (ast.Name, ast.Attribute)):
                        scope.bind_canonical_type(dotted_name(target), class_target)
        if type_name:
            for target in targets:
                if isinstance(target, (ast.Name, ast.Attribute)):
                    scope.bind_type(dotted_name(target), type_name)

    def _class_ref_for_constructor(self, target: TargetRef | None) -> TargetRef | None:
        if target is None:
            return None
        kind, identity = target
        if kind == "constructor":
            return "class", identity
        if kind == "method":
            for module in self.modules:
                for class_info in module.classes:
                    if any(id(method) == identity and method.name == "__init__" for method in class_info.methods):
                        return self._class_ref(class_info)
        return None

    def resolve_target(
        self, target: ast.expr, module: ModuleInfo, scope: Scope, owner: ClassInfo | None
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
                    class_info = owner
                    if class_info and any(item.name == target.attr for item in class_info.methods):
                        return f"{owner.name}.{target.attr}"
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

    def canonical_target(
        self, target: ast.expr, module: ModuleInfo, scope: Scope, owner: ClassInfo | None
    ) -> TargetRef | None:
        """Resolve only targets backed by a known project declaration."""
        imported = self._canonical_import_target(target, scope)
        if imported is not None:
            return imported
        if isinstance(target, ast.Name):
            return scope.internal_target_for(target.id, target)
        if not isinstance(target, ast.Attribute):
            return None
        if isinstance(target.value, ast.Name) and target.value.id == "self" and owner:
            method = next((item for item in reversed(owner.methods) if item.name == target.attr), None)
            if method is not None:
                return self._function_ref(method)
            return None
        base = dotted_name(target.value)
        inferred = scope.canonical_type_of(base)
        if inferred is None:
            type_name = scope.type_of(base)
            if type_name:
                inferred = self._class_target_for_type(type_name, module, scope)
        if inferred is not None:
            class_info = next(
                (item for candidate in self.modules for item in candidate.classes if self._class_ref(item) == inferred),
                None,
            )
            method = next(
                (item for item in reversed(class_info.methods) if item.name == target.attr),
                None,
            ) if class_info else None
            if method is not None:
                return self._function_ref(method)
        return None

    def _canonical_import_target(self, target: ast.expr, scope: Scope) -> TargetRef | None:
        root_node = self._root_name(target)
        if root_node is None or scope.expression_shadows(root_node.id, root_node):
            return None
        imported = scope.canonical_import_for(root_node.id)
        if not imported or not imported.local_module:
            return None
        if isinstance(target, ast.Name):
            if not imported.module:
                return None
            return self._exact_member_ref(imported.local_module, imported.object_name)
        if not isinstance(target, ast.Attribute):
            return None
        syntax = dotted_name(target)
        _, *attributes = syntax.split(".")
        imported_module = self.effective_modules.get(imported.local_module)
        imported_class = (
            self._bound_class(imported_module, imported.object_name)
            if imported_module is not None else None
        )
        if imported.module and imported_class is not None:
            semantic = ".".join([imported.local_module, imported.object_name, *attributes])
        elif imported.module == "" and not imported.asname:
            semantic = syntax
        else:
            semantic = ".".join([imported.local_module, *attributes])
        parts = semantic.split(".")
        for boundary in range(len(parts) - 1, 0, -1):
            exact = self._exact_member_ref(
                ".".join(parts[:boundary]), ".".join(parts[boundary:])
            )
            if exact is not None:
                return exact
        return None

    def _resolution(
        self, target: ast.expr, scope: Scope, exact: TargetRef | None
    ) -> str:
        if exact is not None:
            return "exact"
        root = self._root_name(target)
        if root is not None:
            if scope.expression_shadows(root.id, root):
                return "dynamic"
            imported = scope.canonical_import_for(root.id)
            if imported is not None:
                return imported.resolution if imported.resolution != "exact" else "unresolved"
        if isinstance(target, ast.Name):
            if scope.shadows_import(target.id, target):
                return "dynamic"
            return "unresolved"
        if isinstance(target, ast.Attribute):
            return "dynamic"
        return "dynamic"

    def expression_value(
        self, node: ast.expr, module: ModuleInfo, scope: Scope, owner: ClassInfo | None
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
        self, node: ast.Call, module: ModuleInfo, scope: Scope, owner: ClassInfo | None
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
