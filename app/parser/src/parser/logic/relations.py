"""Resolve canonical object relations without changing the legacy projection."""
from __future__ import annotations

import ast

from .models import ClassInfo, FieldAccessInfo, FieldInfo, ImportInfo, ModuleInfo, TypeReferenceInfo
from .project_index import ProjectIndex

_WRAPPERS = {
    "list", "dict", "set", "tuple", "type", "frozenset",
    "List", "Dict", "Set", "Tuple", "Optional", "Union", "Literal",
    "ClassVar", "Final", "Annotated", "Sequence", "Mapping", "Iterable",
    "Callable", "Type", "Generic", "Protocol", "Any",
}
_NON_TYPE_ARGUMENT_WRAPPERS = {"Literal"}
_FIRST_TYPE_ARGUMENT_WRAPPERS = {"Annotated"}
_BUILTIN_TYPES = {"int", "str", "bool", "float", "bytes", "complex", "object", "None"}


class _FieldAccessVisitor(ast.NodeVisitor):
    def __init__(self, names: dict[str, FieldInfo]) -> None:
        self.names = names
        self.found: list[tuple[ast.Attribute, FieldInfo]] = []

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if (isinstance(node.ctx, ast.Load) and isinstance(node.value, ast.Name)
                and node.value.id == "self" and node.attr in self.names):
            self.found.append((node, self.names[node.attr]))
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return


class _ConditionalBindingVisitor(ast.NodeVisitor):
    """Find names that a module-level compound statement may rebind."""

    def __init__(self) -> None:
        self.names: set[str] = set()

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.names.add(node.id)

    def visit_Import(self, node: ast.Import) -> None:
        self.names.update(alias.asname or alias.name.split(".", 1)[0] for alias in node.names)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self.names.update(alias.asname or alias.name for alias in node.names if alias.name != "*")

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.names.add(node.name)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.names.add(node.name)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name:
            self.names.add(node.name)
        self.generic_visit(node)

    def visit_MatchAs(self, node: ast.MatchAs) -> None:
        if node.name:
            self.names.add(node.name)
        self.generic_visit(node)

    def visit_MatchStar(self, node: ast.MatchStar) -> None:
        if node.name:
            self.names.add(node.name)

    def visit_MatchMapping(self, node: ast.MatchMapping) -> None:
        if node.rest:
            self.names.add(node.rest)
        self.generic_visit(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return

    def _skip_comprehension(self, node: ast.AST) -> None:
        return

    visit_ListComp = _skip_comprehension
    visit_SetComp = _skip_comprehension
    visit_DictComp = _skip_comprehension
    visit_GeneratorExp = _skip_comprehension


class _MethodBindingVisitor(ast.NodeVisitor):
    """Collect bindings that make a name local to a direct class method."""

    def __init__(self) -> None:
        self.names: set[str] = set()

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.names.add(node.id)

    def visit_Import(self, node: ast.Import) -> None:
        self.names.update(alias.asname or alias.name.split(".", 1)[0] for alias in node.names)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self.names.update(alias.asname or alias.name for alias in node.names if alias.name != "*")

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.names.add(node.name)
        self._visit_function_declaration(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.names.add(node.name)
        self._visit_function_declaration(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.names.add(node.name)
        for decorator in node.decorator_list:
            self.visit(decorator)
        for base in node.bases:
            self.visit(base)
        for keyword in node.keywords:
            self.visit(keyword.value)
        self._visit_type_param_expressions(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self._visit_argument_declarations(node.args)

    def _visit_function_declaration(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        self._visit_argument_declarations(node.args)
        if node.returns is not None:
            self.visit(node.returns)
        self._visit_type_param_expressions(node)

    def _visit_argument_declarations(self, arguments: ast.arguments) -> None:
        for default in arguments.defaults:
            self.visit(default)
        for default in arguments.kw_defaults:
            if default is not None:
                self.visit(default)
        parameters = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]
        if arguments.vararg is not None:
            parameters.append(arguments.vararg)
        if arguments.kwarg is not None:
            parameters.append(arguments.kwarg)
        for parameter in parameters:
            if parameter.annotation is not None:
                self.visit(parameter.annotation)

    def _visit_type_param_expressions(self, node: ast.AST) -> None:
        for parameter in getattr(node, "type_params", ()):
            bound = getattr(parameter, "bound", None)
            if bound is not None:
                self.visit(bound)
            default = getattr(parameter, "default_value", None)
            if default is not None:
                self.visit(default)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name:
            self.names.add(node.name)
        self.generic_visit(node)

    def visit_MatchAs(self, node: ast.MatchAs) -> None:
        if node.name:
            self.names.add(node.name)
        self.generic_visit(node)

    def visit_MatchStar(self, node: ast.MatchStar) -> None:
        if node.name:
            self.names.add(node.name)

    def visit_MatchMapping(self, node: ast.MatchMapping) -> None:
        if node.rest:
            self.names.add(node.rest)
        self.generic_visit(node)

    def visit_Global(self, node: ast.Global) -> None:
        self.names.update(node.names)

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        self.names.update(node.names)

    def _visit_comprehension(self, node: ast.AST) -> None:
        # Comprehension iteration targets have their own scope in Python 3.
        # Expressions are still inspected so a walrus binding is treated
        # conservatively as affecting the containing method.
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
    visit_DictComp = _visit_comprehension
    visit_GeneratorExp = _visit_comprehension


class RelationResolver:
    def __init__(self, modules: list[ModuleInfo], index: ProjectIndex) -> None:
        self.modules = modules
        self.index = index
        self.classes = {
            (module.module, item.name): item
            for module in index.by_module.values()
            for item in module.classes
        }

    def resolve_all(self) -> None:
        for module in self.modules:
            module.type_references = []
            module.field_accesses = []
            for class_info in module.classes:
                class_info.resolved_parents = []
                for node in class_info.parent_nodes:
                    self._add_expression(
                        module, class_info, "base", node, class_info.line,
                        class_info,
                    )
                for field in class_info.fields:
                    if field.annotation_node is not None:
                        self._add_expression(
                            module, field, "field_type", field.annotation_node,
                            class_info.line, class_info,
                        )
                    elif isinstance(field.value_node, ast.Call):
                        self._add_expression(
                            module, field, "field_type", field.value_node.func,
                            class_info.line, class_info,
                        )
                self._field_accesses(module, class_info)

    def _field_accesses(self, module: ModuleInfo, owner: ClassInfo) -> None:
        names = {field.name: field for field in owner.fields}
        for method in owner.methods:
            if method.node is None:
                continue
            visitor = _FieldAccessVisitor(names)
            for statement in method.node.body:
                visitor.visit(statement)
            for node, field in visitor.found:
                module.field_accesses.append(FieldAccessInfo(
                    method=method, field=field, file=module.file,
                    line=node.lineno, column=node.col_offset,
                ))

    def _add_expression(self, module: ModuleInfo, owner: ClassInfo | FieldInfo,
                        role: str, node: ast.expr,
                        declaration_cutoff: int | None,
                        class_owner: ClassInfo | None = None) -> None:
        class_statement = self._containing_class_statement(class_owner, node)
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            original = node
            try:
                node = ast.parse(node.value, mode="eval").body
            except SyntaxError:
                self._append(module, owner, role, node.value, node, "unresolved")
                return
            ast.copy_location(node, original)
        seen: set[tuple[str, int]] = set()
        for candidate in self._type_nodes(node):
            expression = ast.unparse(candidate)
            resolution, target = self._resolve(
                module, candidate, declaration_cutoff, class_owner, class_statement
            )
            key = (expression, id(target) if target is not None else 0)
            if resolution == "exact" and key in seen:
                continue
            seen.add(key)
            self._append(module, owner, role, expression, candidate, resolution, target)
            if role == "base" and target is not None and target not in owner.resolved_parents:
                owner.resolved_parents.append(target)

    def _type_nodes(self, node: ast.expr) -> list[ast.expr]:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            try:
                parsed = ast.parse(node.value, mode="eval").body
            except SyntaxError:
                return [node]
            ast.copy_location(parsed, node)
            return self._type_nodes(parsed)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            return self._type_nodes(node.left) + self._type_nodes(node.right)
        if isinstance(node, (ast.Tuple, ast.List)):
            return [item for child in node.elts for item in self._type_nodes(child)]
        if isinstance(node, ast.Subscript):
            wrapper = self._name(node.value).rsplit(".", 1)[-1]
            if wrapper in _NON_TYPE_ARGUMENT_WRAPPERS:
                return []
            if wrapper in _FIRST_TYPE_ARGUMENT_WRAPPERS:
                first = node.slice.elts[0] if isinstance(node.slice, ast.Tuple) else node.slice
                return self._type_nodes(first)
            result = [] if wrapper in _WRAPPERS else [node.value]
            return result + self._type_nodes(node.slice)
        if isinstance(node, (ast.Name, ast.Attribute)):
            if self._name(node).rsplit(".", 1)[-1] in _WRAPPERS:
                return []
            return [node]
        return [node]

    @staticmethod
    def _name(node: ast.expr) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            prefix = RelationResolver._name(node.value)
            return f"{prefix}.{node.attr}" if prefix else node.attr
        return ""

    def _resolve(
        self, module: ModuleInfo, node: ast.expr,
        declaration_cutoff: int | None,
        class_owner: ClassInfo | None = None,
        class_statement: ast.stmt | None = None,
    ) -> tuple[str, ClassInfo | None]:
        name = self._name(node)
        if not name:
            return "unresolved", None
        parts = name.split(".")
        if self._class_type_param_binds(class_owner, parts[0]):
            return "unresolved", None
        if self._method_binds(class_statement, parts[0]):
            return "unresolved", None
        class_binding = self._class_binding_before(
            class_owner, parts[0], class_statement
        )
        if class_binding is not None:
            binding_kind, binding = class_binding
        else:
            binding_kind, binding = self._module_binding_before(
                module, parts[0], declaration_cutoff
            )
        if len(parts) == 1 and binding_kind == "class":
            return "exact", binding
        if binding_kind != "import" or binding is None:
            builtin = binding_kind is None and len(parts) == 1 and parts[0] in _BUILTIN_TYPES
            return ("external", None) if builtin else ("unresolved", None)
        imported = binding
        if imported.from_lib or imported.local_module is None:
            return "external", None
        class_name = imported.object_name if imported.module and len(parts) == 1 else parts[-1]
        target = self.classes.get((imported.local_module, class_name))
        return ("exact", target) if target is not None else ("unresolved", None)

    @staticmethod
    def _method_binds(statement: ast.stmt | None, name: str) -> bool:
        if not isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return False
        arguments = statement.args
        parameters = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]
        if any(parameter.arg == name for parameter in parameters):
            return True
        if arguments.vararg is not None and arguments.vararg.arg == name:
            return True
        if arguments.kwarg is not None and arguments.kwarg.arg == name:
            return True
        if any(parameter.name == name for parameter in getattr(statement, "type_params", ())):
            return True
        visitor = _MethodBindingVisitor()
        for method_statement in statement.body:
            visitor.visit(method_statement)
        return name in visitor.names

    @staticmethod
    def _class_type_param_binds(owner: ClassInfo | None, name: str) -> bool:
        return bool(
            owner is not None
            and owner.node is not None
            and any(
                parameter.name == name
                for parameter in getattr(owner.node, "type_params", ())
            )
        )

    @staticmethod
    def _containing_class_statement(
        owner: ClassInfo | None, node: ast.AST,
    ) -> ast.stmt | None:
        """Find the direct class-suite statement whose evaluation owns ``node``."""
        if owner is None or owner.node is None:
            return None
        for statement in owner.node.body:
            if any(child is node for child in ast.walk(statement)):
                return statement
        return None

    def _class_binding_before(
        self, owner: ClassInfo | None, name: str, cutoff: ast.stmt | None,
    ) -> tuple[str, ClassInfo | ImportInfo | None] | None:
        """Return a proven class-namespace binding before a field expression.

        Class-suite imports and nested classes are deliberately conservative:
        they are not represented by the module index, but they still shadow a
        module binding and therefore must prevent a false exact edge.
        """
        if owner is None or owner.node is None or cutoff is None:
            return None
        binding: tuple[str, ClassInfo | ImportInfo | None] | None = None
        for statement in owner.node.body:
            if statement is cutoff:
                break
            bound_names: set[str] = set()
            if isinstance(statement, ast.Import):
                bound_names.update(
                    alias.asname or alias.name.split(".", 1)[0]
                    for alias in statement.names
                )
            elif isinstance(statement, ast.ImportFrom):
                bound_names.update(
                    alias.asname or alias.name
                    for alias in statement.names if alias.name != "*"
                )
            elif isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                bound_names.add(statement.name)
            else:
                targets: list[ast.AST] = []
                if isinstance(statement, ast.Assign):
                    targets = list(statement.targets)
                elif isinstance(statement, (ast.AnnAssign, ast.AugAssign)):
                    targets = [statement.target]
                elif isinstance(statement, ast.Delete):
                    targets = list(statement.targets)
                bound_names.update(
                    bound_name for target in targets
                    for bound_name in self._target_names(target)
                )
                visitor = _ConditionalBindingVisitor()
                visitor.visit(statement)
                bound_names.update(visitor.names)
            if name in bound_names:
                binding = ("other", None)
        return binding

    @staticmethod
    def _target_names(target: ast.AST) -> set[str]:
        if isinstance(target, ast.Name):
            return {target.id}
        if isinstance(target, (ast.Tuple, ast.List)):
            return {
                name for item in target.elts
                for name in RelationResolver._target_names(item)
            }
        if isinstance(target, ast.Starred):
            return RelationResolver._target_names(target.value)
        return set()

    def _module_binding_before(
        self, module: ModuleInfo, name: str, cutoff: int | None,
    ) -> tuple[str | None, ClassInfo | ImportInfo | None]:
        """Return the last proven direct module binding before a class statement."""
        binding: tuple[str | None, ClassInfo | ImportInfo | None] = (None, None)
        imports = {(item.line, item.local_name): item for item in module.imports}
        classes = {
            id(item.node): item for item in module.classes if item.node is not None
        }
        for statement in module.tree.body:
            if cutoff is not None and getattr(statement, "lineno", cutoff) >= cutoff:
                break
            if isinstance(statement, ast.Import):
                for alias in statement.names:
                    local_name = alias.asname or alias.name.split(".", 1)[0]
                    if local_name == name:
                        binding = ("import", imports.get((statement.lineno, local_name)))
            elif isinstance(statement, ast.ImportFrom):
                for alias in statement.names:
                    local_name = alias.asname or alias.name
                    if alias.name != "*" and local_name == name:
                        binding = ("import", imports.get((statement.lineno, local_name)))
            elif isinstance(statement, ast.ClassDef) and statement.name == name:
                binding = ("class", classes.get(id(statement)))
            elif isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)) and statement.name == name:
                binding = ("other", None)
            else:
                targets: list[ast.AST] = []
                if isinstance(statement, ast.Assign):
                    targets = list(statement.targets)
                elif isinstance(statement, (ast.AnnAssign, ast.AugAssign)):
                    targets = [statement.target]
                elif isinstance(statement, ast.Delete):
                    targets = list(statement.targets)
                elif isinstance(statement, ast.Expr) and isinstance(statement.value, ast.NamedExpr):
                    targets = [statement.value.target]
                if any(name in self._target_names(target) for target in targets):
                    binding = ("other", None)
                elif isinstance(statement, (
                    ast.If, ast.For, ast.AsyncFor, ast.While, ast.With,
                    ast.AsyncWith, ast.Try, ast.TryStar, ast.Match,
                )):
                    visitor = _ConditionalBindingVisitor()
                    visitor.visit(statement)
                    if name in visitor.names:
                        # A path-sensitive binding is not sufficient provenance
                        # for an exact type edge, nor can an earlier import stay
                        # exact when that path may shadow it.
                        binding = ("other", None)
        return binding

    @staticmethod
    def _append(module: ModuleInfo, owner: ClassInfo | FieldInfo, role: str,
                expression: str, node: ast.AST, resolution: str,
                target: ClassInfo | None = None) -> None:
        module.type_references.append(TypeReferenceInfo(
            owner=owner, role=role, expression=expression, resolution=resolution,
            target=target, file=module.file,
            line=getattr(node, "lineno", None), column=getattr(node, "col_offset", None),
        ))
