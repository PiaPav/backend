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
    args: list[CallArgumentInfo] = field(default_factory=list)
    file: Path | None = None
    line: int | None = None
    column: int | None = None


@dataclass(slots=True)
class FieldInfo:
    name: str
    annotation: Any = None
    value: Any = None
    value_node: ast.expr | None = None
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
class FunctionInfo:
    name: str
    args: list[ArgumentInfo] = field(default_factory=list)
    return_type: Any = None
    calls: list[CallInfo] = field(default_factory=list)
    decorators: list[str] = field(default_factory=list)
    metrics: FunctionMetricsInfo = field(default_factory=FunctionMetricsInfo)
    node: ast.FunctionDef | ast.AsyncFunctionDef | None = None
    owner: str | None = None
    file: Path | None = None
    line: int | None = None
    column: int | None = None


@dataclass(slots=True)
class ClassInfo:
    name: str
    parents: list[str] = field(default_factory=list)
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

    @property
    def local_name(self) -> str:
        return self.asname or self.object_name


@dataclass(slots=True)
class ModuleInfo:
    name: str
    module: str
    package: str
    relative_path: Path
    file: Path
    tree: ast.Module
    imports: list[ImportInfo] = field(default_factory=list)
    constants: list[FieldInfo] = field(default_factory=list)
    classes: list[ClassInfo] = field(default_factory=list)
    functions: list[FunctionInfo] = field(default_factory=list)
    calls: list[CallInfo] = field(default_factory=list)

    @property
    def import_aliases(self) -> dict[str, ImportInfo]:
        return {item.local_name: item for item in self.imports}
