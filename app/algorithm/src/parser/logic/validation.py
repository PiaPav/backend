"""Public graph integrity checks."""

from __future__ import annotations

import json
from typing import Any

from .errors import GraphValidationError

CLASS_TYPES = {"class", "dataclass", "enum", "abstract"}


def validate_graph(graph: dict[str, Any]) -> None:
    if not isinstance(graph.get("body"), list):
        raise GraphValidationError("Graph must contain a body list")
    seen: set[tuple[str, str]] = set()
    for wrapper in graph["body"]:
        file = wrapper.get("file") if isinstance(wrapper, dict) else None
        if not isinstance(file, dict):
            raise GraphValidationError("Every body item must contain a file object")
        key = (file.get("path"), file.get("name"))
        if key in seen:
            raise GraphValidationError(f"Duplicate file: {key}")
        seen.add(key)
        path_parts = file.get("path_parts")
        if not isinstance(path_parts, list) or not all(
            isinstance(part, str) and part for part in path_parts
        ):
            raise GraphValidationError(f"File {key} has invalid path_parts")
        if ".".join(path_parts) != file.get("path"):
            raise GraphValidationError(f"File {key} has inconsistent directory path")
        if not isinstance(file.get("imports"), list):
            raise GraphValidationError(f"File {key} has no imports list")
        for imported in file["imports"]:
            if not imported.get("object") or not isinstance(imported.get("from_lib"), bool):
                raise GraphValidationError(f"Invalid import in {key}: {imported!r}")
        for class_info in file.get("classes", []):
            if class_info.get("type") not in CLASS_TYPES:
                raise GraphValidationError(
                    f"Invalid class type in {key}: {class_info.get('type')!r}"
                )
            if not isinstance(class_info.get("methods"), list):
                raise GraphValidationError(f"Invalid methods in {key}")
            _validate_functions(class_info["methods"], key)
        _validate_functions(file.get("functions", []), key)
    try:
        json.dumps(graph, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise GraphValidationError(f"Graph is not JSON serializable: {exc}") from exc


def _validate_functions(functions: Any, key: tuple[str, str]) -> None:
    if not isinstance(functions, list):
        raise GraphValidationError(f"Invalid functions in {key}")
    for function in functions:
        metrics = function.get("metrics") if isinstance(function, dict) else None
        if not isinstance(metrics, dict):
            raise GraphValidationError(f"Function in {key} has no metrics")
        cyclomatic = metrics.get("cyclomatic_complexity")
        if not isinstance(cyclomatic, int) or cyclomatic < 1:
            raise GraphValidationError(f"Invalid function complexity in {key}")
