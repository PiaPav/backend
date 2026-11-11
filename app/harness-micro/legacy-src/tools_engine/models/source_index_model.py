from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

SourceKind = Literal[
    "class",
    "method",
    "function",
    "field",
    "constant",
]


@dataclass(slots=True, frozen=True)
class SourceSpan:
    start_line: int
    start_column: int
    end_line: int
    end_column: int
    start_byte: int
    end_byte: int

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SourceSpan:
        return cls(
            start_line=data["start_line"],
            start_column=data["start_column"],
            end_line=data["end_line"],
            end_column=data["end_column"],
            start_byte=data["start_byte"],
            end_byte=data["end_byte"],
        )


@dataclass(slots=True)
class SourceSymbol:
    source_id: str
    kind: SourceKind
    name: str
    qualified_name: str
    file: str
    parent_id: str | None
    span: SourceSpan

    # Заполняются только у символов kind="class".
    methods: dict[str, list[str]] = field(default_factory=dict)
    fields: dict[str, list[str]] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SourceSymbol:
        return cls(
            source_id=data["source_id"],
            kind=data["kind"],
            name=data["name"],
            qualified_name=data["qualified_name"],
            file=data["file"],
            parent_id=data.get("parent_id"),
            span=SourceSpan.from_dict(data["span"]),
            methods=data.get("methods", {}),
            fields=data.get("fields", {}),
        )


@dataclass(slots=True, frozen=True)
class SourceFile:
    relative_path: str
    name: str
    module: str
    sha256: str
    size_bytes: int
    encoding: str

    # Имя структуры -> source_id найденных объявлений.
    classes: dict[str, list[str]]
    functions: dict[str, list[str]]
    constants: dict[str, list[str]]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SourceFile:
        return cls(
            relative_path=data["relative_path"],
            name=data["name"],
            module=data["module"],
            sha256=data["sha256"],
            size_bytes=data["size_bytes"],
            encoding=data["encoding"],
            classes=data.get("classes", {}),
            functions=data.get("functions", {}),
            constants=data.get("constants", {}),
        )


@dataclass(slots=True, frozen=True)
class SourceProject:
    root: str
    fingerprint: str
    file_count: int

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SourceProject:
        return cls(
            root=data["root"],
            fingerprint=data["fingerprint"],
            file_count=data["file_count"],
        )


@dataclass(slots=True, frozen=True)
class SourceLookup:
    classes: dict[str, list[str]]
    methods: dict[str, list[str]]
    functions: dict[str, list[str]]
    constants: dict[str, list[str]]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SourceLookup:
        return cls(
            classes=data.get("classes", {}),
            methods=data.get("methods", {}),
            functions=data.get("functions", {}),
            constants=data.get("constants", {}),
        )


@dataclass(slots=True)
class SourceIndex:
    schema_version: int
    project: SourceProject

    # Базовое имя файла -> относительные пути.
    files_by_name: dict[str, list[str]]

    # Относительный путь -> описание файла.
    files: dict[str, SourceFile]

    # source_id -> описание структуры.
    symbols: dict[str, SourceSymbol]

    lookup: SourceLookup

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SourceIndex:
        return cls(
            schema_version=data["schema_version"],
            project=SourceProject.from_dict(data["project"]),
            files_by_name=data.get("files_by_name", {}),
            files={
                relative_path: SourceFile.from_dict(file_data)
                for relative_path, file_data in data.get("files", {}).items()
            },
            symbols={
                source_id: SourceSymbol.from_dict(symbol_data)
                for source_id, symbol_data in data.get("symbols", {}).items()
            },
            lookup=SourceLookup.from_dict(data.get("lookup", {})),
        )
