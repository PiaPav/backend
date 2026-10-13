"""Conversion of internal analysis facts to the public graph contract."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .calls import CallResolver
from .models import ArgumentInfo, CallInfo, ClassInfo, FieldInfo, FunctionInfo, ModuleInfo


class GraphSerializer:
    def __init__(self, modules: list[ModuleInfo], calls: CallResolver) -> None:
        self.modules = modules
        self.calls = calls

    def serialize(self) -> dict[str, Any]:
        return {"body": [{"file": self._module(item)} for item in self.modules]}

    def _module(self, module: ModuleInfo) -> dict[str, Any]:
        result: dict[str, Any] = {
            "name": module.name,
            "path": module.package,
            "path_parts": list(module.relative_path.parent.parts)
            if module.relative_path.parent != Path(".")
            else [],
            "imports": [
                {
                    "object": item.object_name,
                    **({"asname": item.asname} if item.asname else {}),
                    "path": item.local_module if not item.from_lib else item.module,
                    "from_lib": item.from_lib,
                }
                for item in module.imports
            ],
        }
        if module.classes or module.functions:
            result["classes"] = [self._class(item, module) for item in module.classes]
        if module.constants:
            result["constants"] = [self._field(item) for item in module.constants]
        if module.functions:
            result["functions"] = [self._function(item, module) for item in module.functions]
        if module.calls:
            result["calls"] = [self._call(item, module, None) for item in module.calls]
        return result

    def _class(self, item: ClassInfo, module: ModuleInfo) -> dict[str, Any]:
        return {
            "name": item.name,
            "parent": item.parents[0] if len(item.parents) == 1 else (item.parents or None),
            "type": item.kind,
            "fields": [self._field(field) for field in item.fields],
            "methods": [self._function(method, module) for method in item.methods],
        }

    @staticmethod
    def _field(item: FieldInfo) -> dict[str, Any]:
        return {"name": item.name, "type": item.annotation, "value": item.value}

    @staticmethod
    def _argument(item: ArgumentInfo) -> dict[str, Any]:
        return {"name": item.name, "type": item.annotation, "value": item.default}

    def _function(self, item: FunctionInfo, module: ModuleInfo) -> dict[str, Any]:
        result: dict[str, Any] = {
            "name": item.name,
            "args": [self._argument(argument) for argument in item.args],
            "return_type": item.return_type,
            "metrics": asdict(item.metrics),
        }
        if item.calls:
            result["calls"] = [self._call(call, module, item.owner) for call in item.calls]
        return result

    def _call(
        self, item: CallInfo, module: ModuleInfo, owner: str | None
    ) -> dict[str, Any]:
        return {
            "object": item.object_name,
            "args": [
                {
                    "name": argument.name,
                    "value": argument.value,
                }
                for argument in item.args
            ],
        }


def save_graph(graph: dict[str, Any], output_path: str | Path) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(graph, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
