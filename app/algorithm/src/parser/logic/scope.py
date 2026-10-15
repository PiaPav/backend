"""Per-analysis lexical state used during call resolution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Scope:
    parent: "Scope | None" = None
    owner_class: Any = None
    variables: dict[str, str] = field(default_factory=dict)
    lexical_bindings: set[str] = field(default_factory=set)
    import_suppressions: set[str] = field(default_factory=set)
    expression_bindings: dict[int, frozenset[str]] = field(default_factory=dict)
    active_imports: dict[str, Any] = field(default_factory=dict)
    canonical_imports: dict[str, Any] = field(default_factory=dict)
    internal_targets: dict[str, tuple[str, int]] = field(default_factory=dict)
    canonical_types: dict[str, tuple[str, int]] = field(default_factory=dict)
    canonical_type_parameters: set[str] = field(default_factory=set)

    def fork(self) -> "Scope":
        """Copy mutable flow state while retaining the same lexical parent."""
        return Scope(
            parent=self.parent,
            owner_class=self.owner_class,
            variables=dict(self.variables),
            lexical_bindings=set(self.lexical_bindings),
            import_suppressions=set(self.import_suppressions),
            expression_bindings=dict(self.expression_bindings),
            active_imports=dict(self.active_imports),
            canonical_imports=dict(self.canonical_imports),
            internal_targets=dict(self.internal_targets),
            canonical_types=dict(self.canonical_types),
            canonical_type_parameters=set(self.canonical_type_parameters),
        )

    def merge_flows(self, branches: list["Scope"]) -> None:
        """Keep only bindings whose values agree on every reachable branch."""
        if not branches:
            return
        for attribute in ("variables", "active_imports", "canonical_imports", "internal_targets", "canonical_types"):
            mappings = [getattr(branch, attribute) for branch in branches]
            def same(left: Any, right: Any) -> bool:
                if attribute != "canonical_imports":
                    return left == right
                fields = ("module", "object_name", "asname", "local_module", "level")
                return all(getattr(left, field, None) == getattr(right, field, None) for field in fields)
            common = {
                key: value
                for key, value in mappings[0].items()
                if all(key in mapping and same(mapping[key], value) for mapping in mappings[1:])
            }
            setattr(self, attribute, common)
        self.lexical_bindings = set.union(*(branch.lexical_bindings for branch in branches))
        self.import_suppressions = set.union(*(branch.import_suppressions for branch in branches))
        self.canonical_type_parameters = set.union(*(
            branch.canonical_type_parameters for branch in branches
        ))

    def bind_name(self, name: str) -> None:
        self.invalidate_type(name)
        self.lexical_bindings.add(name)
        self.active_imports.pop(name, None)
        self.canonical_imports.pop(name, None)
        self.internal_targets.pop(name, None)
        self.canonical_types.pop(name, None)

    def bind_internal(self, name: str, target: tuple[str, int]) -> None:
        self.bind_name(name)
        self.internal_targets[name] = target

    def bind_import(self, name: str, imported: Any) -> None:
        self.lexical_bindings.discard(name)
        self.import_suppressions.discard(name)
        self.internal_targets.pop(name, None)
        self.canonical_types.pop(name, None)
        self.active_imports[name] = imported
        self.canonical_imports[name] = imported

    def bind_canonical_import(self, name: str, imported: Any) -> None:
        self.internal_targets.pop(name, None)
        self.canonical_types.pop(name, None)
        self.canonical_imports[name] = imported

    def canonical_import_for(self, name: str) -> Any:
        scope: Scope | None = self
        while scope is not None:
            if name in scope.canonical_imports:
                return scope.canonical_imports[name]
            if name in scope.lexical_bindings or name in scope.import_suppressions:
                return None
            scope = scope.parent
        return None

    def import_for(self, name: str) -> Any:
        scope: Scope | None = self
        while scope is not None:
            if name in scope.lexical_bindings or name in scope.import_suppressions:
                return None
            if name in scope.active_imports:
                return scope.active_imports[name]
            scope = scope.parent
        return None

    def bind_type(self, name: str, type_name: str) -> None:
        self.variables[name] = type_name

    def bind_canonical_type(self, name: str, target: tuple[str, int]) -> None:
        self.canonical_types[name] = target

    def canonical_type_of(self, name: str) -> tuple[str, int] | None:
        scope: Scope | None = self
        while scope is not None:
            if name in scope.canonical_types:
                return scope.canonical_types[name]
            if name.split(".", 1)[0] in scope.lexical_bindings:
                return None
            scope = scope.parent
        return None

    def is_canonical_type_parameter(self, name: str) -> bool:
        scope: Scope | None = self
        while scope is not None:
            if name in scope.canonical_type_parameters:
                return True
            scope = scope.parent
        return False

    def internal_target_for(self, name: str, node: object | None = None) -> tuple[str, int] | None:
        scope: Scope | None = self
        while scope is not None:
            if node is not None and name in scope.expression_bindings.get(id(node), ()):
                return None
            if name in scope.internal_targets:
                return scope.internal_targets[name]
            if name in scope.lexical_bindings or name in scope.import_suppressions:
                return None
            scope = scope.parent
        return None

    def type_of(self, name: str) -> str | None:
        scope: Scope | None = self
        while scope is not None:
            if name in scope.variables:
                return scope.variables[name]
            if name.split(".", 1)[0] in scope.lexical_bindings:
                return None
            scope = scope.parent
        return None

    def invalidate_type(self, name: str) -> None:
        """Discard a type and all conservative dotted descendants."""
        prefix = f"{name}."
        for mapping in (self.variables, self.canonical_types):
            for key in list(mapping):
                if key == name or key.startswith(prefix):
                    mapping.pop(key, None)

    def shadows_import(self, name: str, node: object | None = None) -> bool:
        """Whether a lexical binding hides a module-level import alias."""
        scope: Scope | None = self
        while scope is not None:
            if name in scope.lexical_bindings or name in scope.import_suppressions:
                return True
            if node is not None and name in scope.expression_bindings.get(id(node), ()):
                return True
            scope = scope.parent
        return False
