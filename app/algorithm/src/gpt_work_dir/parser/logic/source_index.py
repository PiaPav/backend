"""Build and save a direct-lookup index for analyzed Python sources."""

from __future__ import annotations

import ast
import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .models import ModuleInfo

SCHEMA_VERSION = 1


class SourceIndexBuilder:
    """Create source references without changing the public graph contract."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.files: dict[str, dict[str, Any]] = {}
        self.files_by_name: dict[str, list[str]] = {}
        self.line_byte_offsets: dict[str, list[int]] = {}
        self.symbols: dict[str, dict[str, Any]] = {}
        self.lookup: dict[str, dict[str, list[str]]] = {
            "classes": {},
            "methods": {},
            "functions": {},
            "constants": {},
        }

    def build(self) -> dict[str, Any]:
        for paths in self.files_by_name.values():
            paths.sort()
        return {
            "schema_version": SCHEMA_VERSION,
            "project": {
                "root": str(self.root),
                "fingerprint": self._project_fingerprint(self.files),
                "file_count": len(self.files),
            },
            "files_by_name": dict(sorted(self.files_by_name.items())),
            "files": self.files,
            "symbols": self.symbols,
            "lookup": self.lookup,
        }

    def start_module(self, module: ModuleInfo) -> Callable[[ast.stmt], None]:
        """Register a file and return a collector for the definition pass."""
        relative_path = module.relative_path.as_posix()
        file_record: dict[str, Any] = {
            "relative_path": relative_path,
            "name": module.relative_path.name,
            "module": module.module,
            "sha256": hashlib.sha256(module.source_bytes).hexdigest(),
            "size_bytes": len(module.source_bytes),
            "encoding": "utf-8-sig" if module.byte_order_mark_size else "utf-8",
            "classes": {},
            "functions": {},
            "constants": {},
        }
        self.files[relative_path] = file_record
        self.files_by_name.setdefault(module.relative_path.name, []).append(relative_path)
        self.line_byte_offsets[relative_path] = self._line_byte_offsets(module)
        return lambda node: self._index_node(module, file_record, node)

    def _index_node(
        self, module: ModuleInfo, file_record: dict[str, Any], node: ast.stmt
    ) -> None:
        relative_path = module.relative_path.as_posix()
        if isinstance(node, ast.ClassDef):
            class_id = self._add_symbol(
                module, node, "class", node.name, node.name, parent_id=None
            )
            self._append(file_record["classes"], node.name, class_id)
            self._append(
                self.lookup["classes"], f"{relative_path}::{node.name}", class_id
            )
            class_symbol = self.symbols[class_id]
            class_symbol["methods"] = {}
            class_symbol["fields"] = {}
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    method_id = self._add_symbol(
                        module,
                        child,
                        "method",
                        child.name,
                        f"{node.name}.{child.name}",
                        parent_id=class_id,
                    )
                    self._append(class_symbol["methods"], child.name, method_id)
                    self._append(
                        self.lookup["methods"],
                        f"{relative_path}::{node.name}::{child.name}",
                        method_id,
                    )
                elif isinstance(child, (ast.Assign, ast.AnnAssign)):
                    for name in self._assigned_names(child):
                        field_id = self._add_symbol(
                            module,
                            child,
                            "field",
                            name,
                            f"{node.name}.{name}",
                            parent_id=class_id,
                        )
                        self._append(class_symbol["fields"], name, field_id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            function_id = self._add_symbol(
                module, node, "function", node.name, node.name, parent_id=None
            )
            self._append(file_record["functions"], node.name, function_id)
            self._append(
                self.lookup["functions"],
                f"{relative_path}::{node.name}",
                function_id,
            )
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            for name in self._assigned_names(node):
                constant_id = self._add_symbol(
                    module, node, "constant", name, name, parent_id=None
                )
                self._append(file_record["constants"], name, constant_id)
                self._append(
                    self.lookup["constants"],
                    f"{relative_path}::{name}",
                    constant_id,
                )

    def _add_symbol(
        self,
        module: ModuleInfo,
        node: ast.AST,
        kind: str,
        name: str,
        qualified_name: str,
        parent_id: str | None,
    ) -> str:
        span = self._span(module, node)
        relative_path = module.relative_path.as_posix()
        source_id = f"{relative_path}::{kind}:{qualified_name}@{span['start_line']}"
        self.symbols[source_id] = {
            "source_id": source_id,
            "kind": kind,
            "name": name,
            "qualified_name": qualified_name,
            "file": relative_path,
            "parent_id": parent_id,
            "span": span,
        }
        return source_id

    @staticmethod
    def _assigned_names(node: ast.Assign | ast.AnnAssign) -> list[str]:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        return [target.id for target in targets if isinstance(target, ast.Name)]

    @staticmethod
    def _append(mapping: dict[str, list[str]], key: str, source_id: str) -> None:
        mapping.setdefault(key, []).append(source_id)

    def _span(self, module: ModuleInfo, node: ast.AST) -> dict[str, int]:
        start_line = getattr(node, "lineno", 1)
        start_column = getattr(node, "col_offset", 0)
        decorators = getattr(node, "decorator_list", [])
        if decorators:
            first = min(decorators, key=lambda item: (item.lineno, item.col_offset))
            start_line = first.lineno
            start_column = max(0, first.col_offset - 1)
        end_line = getattr(node, "end_lineno", start_line)
        end_column = getattr(node, "end_col_offset", start_column)
        line_offsets = self.line_byte_offsets[module.relative_path.as_posix()]
        return {
            "start_line": start_line,
            "start_column": start_column,
            "end_line": end_line,
            "end_column": end_column,
            "start_byte": line_offsets[start_line - 1] + start_column,
            "end_byte": line_offsets[end_line - 1] + end_column,
        }

    @staticmethod
    def _line_byte_offsets(module: ModuleInfo) -> list[int]:
        offsets = [module.byte_order_mark_size]
        current = module.byte_order_mark_size
        for line in module.source.splitlines(keepends=True):
            current += len(line.encode("utf-8"))
            offsets.append(current)
        return offsets

    @staticmethod
    def _project_fingerprint(files: dict[str, dict[str, Any]]) -> str:
        digest = hashlib.sha256()
        for relative_path, file_record in sorted(files.items()):
            digest.update(relative_path.encode("utf-8"))
            digest.update(b"\0")
            digest.update(file_record["sha256"].encode("ascii"))
            digest.update(b"\0")
        return digest.hexdigest()


def save_source_index(index: dict[str, Any], output_path: str | Path) -> None:
    """Save a source index as deterministic UTF-8 JSON."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
