"""Central legacy file identity compatibility projection."""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Any


def legacy_file_id(file: Mapping[str, Any]) -> str:
    if isinstance(file.get("_metric_file_id"), str):
        return file["_metric_file_id"]
    path, name = str(file.get("path") or ""), str(file.get("name") or "unknown")
    return (path or name) if name == "__init__" else ".".join(filter(None, (path, name)))


def semantic_module_name(file: Mapping[str, Any]) -> str:
    """Name used by Python imports, independent of collision-safe file identity."""
    path, name = str(file.get("path") or ""), str(file.get("name") or "")
    return path if name == "__init__" else ".".join(filter(None, (path, name)))


def effective_module_ids(files: list[Mapping[str, Any]]) -> dict[str, str]:
    """Resolve semantic modules deterministically; package initializers win collisions."""
    result: dict[str, str] = {}
    for file in sorted(files, key=lambda item: (item.get("name") != "__init__", legacy_file_id(item))):
        result.setdefault(semantic_module_name(file), legacy_file_id(file))
    return result


def graph_files(graph: Mapping[str, Any]) -> list[dict[str, Any]]:
    files = [dict(item["file"]) for item in graph.get("body", [])
             if isinstance(item, Mapping) and isinstance(item.get("file"), Mapping)]
    bases = Counter(legacy_file_id(file) for file in files)
    for file in files:
        base = legacy_file_id(file)
        if bases[base] > 1:
            parts = [str(part) for part in file.get("path_parts", [])]
            filename = "__init__.py" if file.get("name") == "__init__" else f"{file.get('name')}.py"
            file["_metric_file_id"] = "file:" + "/".join([*parts, filename])
    return files
