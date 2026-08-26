"""Per-analysis lexical state used during call resolution."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class Scope:
    parent: "Scope | None" = None
    owner_class: str | None = None
    variables: dict[str, str] = field(default_factory=dict)

    def bind_type(self, name: str, type_name: str) -> None:
        self.variables[name] = type_name

    def type_of(self, name: str) -> str | None:
        scope: Scope | None = self
        while scope is not None:
            if name in scope.variables:
                return scope.variables[name]
            scope = scope.parent
        return None
