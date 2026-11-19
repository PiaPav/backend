"""Internal analysis facts, independent from the output JSON shape."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class ExpressionInfo:
    value: Any
    file: Path | None = None
    line: int | None = None
    column: int | None = None


@dataclass(slots=True)
class ArgumentInfo:
    name: str
    annotation: Any = None
    default: Any = None
    file: Path | None = None
    line: int | None = None
    column: int | None = None


@dataclass(slots=True)
class CallArgumentInfo:
    name: str
    value_node: ast.expr
    value: Any


@dataclass(slots=True)
class CallInfo:
    node: ast.Call
    object_name: str = ""
    semantic_target: tuple[str, str] | None = None
    args: list[CallArgumentInfo] = field(default_factory=list)
    file: Path | None = None
    line: int | None = None
    column: int | None = None


@dataclass(slots=True)
class CanonicalCallsiteInfo:
    """Canonical call fact kept separate from the legacy call projection."""

    node: ast.Call
    expression: str
    syntactic_depth: int
    awaited: bool
    resolution: str
    target: tuple[str, int] | None = None
    file: Path | None = None
    line: int | None = None
    column: int | None = None


@dataclass(slots=True)
class FieldInfo:
    name: str
    annotation: Any = None
    value: Any = None
    value_node: ast.expr | None = None
    annotation_node: ast.expr | None = None
    annotation_source: str | None = None
    file: Path | None = None
    line: int | None = None
    column: int | None = None


@dataclass(slots=True)
class FunctionMetricsInfo:
    cyclomatic_complexity: int = 1
    cognitive_complexity: int = 0
    max_nesting: int = 0
    lines_of_code: int = 1
    statement_count: int = 0
    return_count: int = 0
    raise_count: int = 0
    await_count: int = 0
    broad_exception_handlers: int = 0
    raised_exceptions: list[str] = field(default_factory=list)
    caught_exceptions: list[str] = field(default_factory=list)
    self_attribute_accesses: list[str] = field(default_factory=list)
    is_async: bool = False


@dataclass(slots=True)
class ComplexityControlFact:
    """One ordered structural event, without a complexity score."""

    kind: str
    line: int
    column: int
    parent_index: int | None = None
    operand_count: int = 0
    case_count: int = 0
    filter_count: int = 0
    expression: str | None = None


@dataclass(slots=True)
class ComplexityOccurrenceFact:
    """One countable callable-scope occurrence."""

    kind: str
    line: int
    column: int
    expression: str | None = None


@dataclass(slots=True)
class FunctionComplexityFacts:
    start_line: int
    start_column: int
    end_line: int
    end_column: int
    is_async: bool
    controls: list[ComplexityControlFact] = field(default_factory=list)
    occurrences: list[ComplexityOccurrenceFact] = field(default_factory=list)


@dataclass(slots=True)
class FunctionInfo:
    name: str
    args: list[ArgumentInfo] = field(default_factory=list)
    return_type: Any = None
    calls: list[CallInfo] = field(default_factory=list)
    canonical_callsites: list[CanonicalCallsiteInfo] = field(default_factory=list)
    decorators: list[str] = field(default_factory=list)
    metrics: FunctionMetricsInfo = field(default_factory=FunctionMetricsInfo)
    complexity_facts: FunctionComplexityFacts | None = None
    node: ast.FunctionDef | ast.AsyncFunctionDef | None = None
    owner: str | None = None
    file: Path | None = None
    line: int | None = None
    column: int | None = None


@dataclass(slots=True)
class ClassInfo:
    name: str
    parents: list[str] = field(default_factory=list)
    parent_nodes: list[ast.expr] = field(default_factory=list)
    resolved_parents: list[ClassInfo] = field(default_factory=list)
    kind: str = "class"
    fields: list[FieldInfo] = field(default_factory=list)
    methods: list[FunctionInfo] = field(default_factory=list)
    decorators: list[str] = field(default_factory=list)
    abstract_methods: set[str] = field(default_factory=set)
    node: ast.ClassDef | None = None
    module: str = ""
    file: Path | None = None
    line: int | None = None
    column: int | None = None


@dataclass(slots=True)
class ImportInfo:
    module: str
    object_name: str
    asname: str | None = None
    local_module: str | None = None
    from_lib: bool = True
    level: int = 0
    file: Path | None = None
    line: int | None = None
    column: int | None = None
    statement_line: int | None = None
    statement_column: int | None = None
    alias_index: int = 0

    @property
    def local_name(self) -> str:
        # ``import a.b.c`` binds ``a``; ``import a.b.c as c`` binds ``c``.
        # From-imports keep binding the imported object itself.
        if self.asname:
            return self.asname
        if not self.module:
            return self.object_name.split(".", 1)[0]
        return self.object_name

    @property
    def resolution(self) -> str:
        if self.local_module is not None:
            return "exact"
        return "unresolved" if self.level else "external"


@dataclass(slots=True)
class TypeReferenceInfo:
    owner: ClassInfo | FieldInfo
    role: str
    expression: str
    resolution: str
    target: ClassInfo | None = None
    candidates: list[ClassInfo] = field(default_factory=list)
    file: Path | None = None
    line: int | None = None
    column: int | None = None


@dataclass(slots=True)
class FieldAccessInfo:
    method: FunctionInfo
    field: FieldInfo
    file: Path | None = None
    line: int | None = None
    column: int | None = None


@dataclass(slots=True)
class ModuleInfo:
    name: str
    module: str
    package: str
    relative_path: Path
    file: Path
    tree: ast.Module
    source: str
    source_bytes: bytes
    byte_order_mark_size: int = 0
    imports: list[ImportInfo] = field(default_factory=list)
    canonical_imports: list[ImportInfo] = field(default_factory=list)
    constants: list[FieldInfo] = field(default_factory=list)
    classes: list[ClassInfo] = field(default_factory=list)
    functions: list[FunctionInfo] = field(default_factory=list)
    calls: list[CallInfo] = field(default_factory=list)
    canonical_callsites: list[CanonicalCallsiteInfo] = field(default_factory=list)
    type_references: list[TypeReferenceInfo] = field(default_factory=list)
    field_accesses: list[FieldAccessInfo] = field(default_factory=list)

    @property
    def import_aliases(self) -> dict[str, ImportInfo]:
        return {item.local_name: item for item in self.imports}
