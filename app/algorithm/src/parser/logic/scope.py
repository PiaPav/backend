"""Per-analysis lexical state used during call resolution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Scope:
    parent: "Scope | None" = None
    owner_class: str | None = None
    variables: dict[str, str] = field(default_factory=dict)
    lexical_bindings: set[str] = field(default_factory=set)
    import_suppressions: set[str] = field(default_factory=set)
    expression_bindings: dict[int, frozenset[str]] = field(default_factory=dict)
    active_imports: dict[str, Any] = field(default_factory=dict)

    def bind_name(self, name: str) -> None:
        self.lexical_bindings.add(name)
        self.active_imports.pop(name, None)

    def bind_import(self, name: str, imported: Any) -> None:
        self.lexical_bindings.discard(name)
        self.import_suppressions.discard(name)
        self.active_imports[name] = imported

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

    def type_of(self, name: str) -> str | None:
        scope: Scope | None = self
        while scope is not None:
            if name in scope.variables:
                return scope.variables[name]
            if name.split(".", 1)[0] in scope.lexical_bindings:
                return None
            scope = scope.parent
        return None

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
