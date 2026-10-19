"""File API for the complete legacy graph metrics implementation."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .logic.calculator import calculate_graph_metrics
from .logic.serialization import _save_metrics_dto
from graph_dto import graph_fingerprint, validate_graph_v1

__all__ = ["calculate_graph_metrics", "calculate_metrics", "load_graph"]


# Kept local deliberately: metrics accepts the legacy Graph DTO without
# depending on the parser package at runtime.
_CLASS_TYPES = {"class", "dataclass", "enum", "abstract"}


def _require_path(value: Path, name: str) -> Path:
    if not isinstance(value, Path):
        raise TypeError(f"{name} must be a pathlib.Path")
    return value


def load_graph(graph_path: Path) -> dict[str, Any]:
    """Load a legacy graph or validated Graph DTO v1."""
    path = _require_path(graph_path, "graph_path").expanduser().resolve()
    return _load_graph_bytes(path.read_bytes())


def _load_graph_bytes(raw: bytes) -> dict[str, Any]:
    """Decode and validate one immutable legacy graph representation."""
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        message = exc.msg if isinstance(exc, json.JSONDecodeError) else str(exc)
        raise ValueError(f"Invalid graph JSON: {message}") from exc
    if not isinstance(data, dict):
        raise ValueError("Graph root must be a JSON object")
    if "schema_version" in data:
        if data["schema_version"] != 1:
            raise ValueError(f"Unsupported graph schema_version: {data['schema_version']!r}")
        validate_graph_v1(data)
        bodyless_semantics = data.get("parser_semantics_version") in {6, 7}
        if not bodyless_semantics and "body" not in data:
            raise ValueError("Graph DTO v1 requires a legacy body mirror in this metrics increment")
        if not bodyless_semantics:
            _validate_legacy_graph({"body": data["body"]})
    else:
        _validate_legacy_graph(data)
    return data


def _canonicalize_legacy_value(value: Any) -> Any:
    """Return a canonical legacy value while preserving list order."""
    if isinstance(value, dict):
        return {
            key: _canonicalize_legacy_value(item)
            for key, item in sorted(value.items())
        }
    if isinstance(value, list):
        items = [_canonicalize_legacy_value(item) for item in value]
        return items
    return value


def _legacy_graph_fingerprint(graph: dict[str, Any]) -> str:
    """Hash the canonical semantic legacy DTO rather than its source bytes."""
    canonical_graph = _canonicalize_legacy_value(graph)
    canonical_graph["body"] = sorted(
        canonical_graph["body"],
        key=lambda item: json.dumps(
            item, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ),
    )
    canonical = json.dumps(
        canonical_graph,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _expect_mapping(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"Expected object at {path}")
    return value


def _expect_list(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"Expected list at {path}")
    return value


def _validate_calls(calls: Any, path: str) -> None:
    for call_index, call in enumerate(_expect_list(calls, path)):
        call_path = f"{path}[{call_index}]"
        call_object = _expect_mapping(call, call_path)
        if "args" not in call_object:
            continue
        for arg_index, argument in enumerate(_expect_list(call_object["args"], f"{call_path}.args")):
            argument_path = f"{call_path}.args[{arg_index}]"
            argument_object = _expect_mapping(argument, argument_path)
            value = argument_object.get("value")
            if isinstance(value, dict) and value.get("type") == "call":
                _validate_calls([value], f"{argument_path}.value")


def _validate_callable(callable_info: Any, path: str) -> None:
    callable_object = _expect_mapping(callable_info, path)
    metrics = _expect_mapping(callable_object.get("metrics"), f"{path}.metrics")
    cyclomatic = metrics.get("cyclomatic_complexity")
    if not isinstance(cyclomatic, int) or cyclomatic < 1:
        raise ValueError(f"Invalid cyclomatic_complexity at {path}.metrics")
    if "calls" in callable_object:
        _validate_calls(callable_object["calls"], f"{path}.calls")


def _validate_legacy_graph(graph: dict[str, Any]) -> None:
    body = _expect_list(graph.get("body"), "body")
    file_list_fields = ("imports", "classes", "functions", "calls", "constants")
    seen_file_ids: set[tuple[str, str]] = set()
    for body_index, wrapper in enumerate(body):
        wrapper_path = f"body[{body_index}]"
        wrapper_object = _expect_mapping(wrapper, wrapper_path)
        file = _expect_mapping(wrapper_object.get("file"), f"{wrapper_path}.file")
        file_path = f"{wrapper_path}.file"

        name = file.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError(f"Expected non-empty string at {file_path}.name")
        module_path = file.get("path")
        if not isinstance(module_path, str):
            raise ValueError(f"Expected string at {file_path}.path")
        path_parts = _expect_list(file.get("path_parts"), f"{file_path}.path_parts")
        if not all(isinstance(part, str) and part for part in path_parts):
            raise ValueError(f"Invalid path_parts at {file_path}.path_parts")
        if ".".join(path_parts) != module_path:
            raise ValueError(f"Inconsistent path and path_parts at {file_path}")

        file_id = (module_path, name)
        if file_id in seen_file_ids:
            raise ValueError(f"Duplicate file: {file_id}")
        seen_file_ids.add(file_id)

        imports = _expect_list(file.get("imports"), f"{file_path}.imports")
        for import_index, imported in enumerate(imports):
            import_path = f"{file_path}.imports[{import_index}]"
            imported_object = _expect_mapping(imported, import_path)
            if not imported_object.get("object") or not isinstance(
                imported_object.get("from_lib"), bool
            ):
                raise ValueError(f"Invalid import at {import_path}")
        for field in file_list_fields:
            if field in file:
                _expect_list(file[field], f"{file_path}.{field}")
        for class_index, class_info in enumerate(file.get("classes", [])):
            class_path = f"{file_path}.classes[{class_index}]"
            class_object = _expect_mapping(class_info, class_path)
            if class_object.get("type") not in _CLASS_TYPES:
                raise ValueError(f"Invalid class type at {class_path}.type")
            for field in ("methods", "fields"):
                if field in class_object:
                    _expect_list(class_object[field], f"{class_path}.{field}")
            _expect_list(class_object.get("methods"), f"{class_path}.methods")
            for method_index, method in enumerate(class_object.get("methods", [])):
                _validate_callable(method, f"{class_path}.methods[{method_index}]")
        for function_index, function in enumerate(file.get("functions", [])):
            _validate_callable(function, f"{wrapper_path}.file.functions[{function_index}]")
        if "calls" in file:
            _validate_calls(file["calls"], f"{wrapper_path}.file.calls")


def calculate_metrics(graph_path: Path, output_path: Path) -> Path:
    """Calculate and atomically persist deterministic Metrics DTO envelope."""
    graph_path = _require_path(graph_path, "graph_path")
    output_path = _require_path(output_path, "output_path")
    source = graph_path.expanduser().resolve()
    raw = source.read_bytes()
    graph = _load_graph_bytes(raw)
    is_v1 = graph.get("schema_version") == 1
    parser_semantics = graph.get("parser_semantics_version") if is_v1 else None
    is_canonical_v2 = parser_semantics in {2, 3, 4, 5, 6, 7}
    is_canonical_v3 = parser_semantics in {3, 4, 5, 6, 7}
    is_bodyless = parser_semantics in {6, 7}
    legacy_body = {"body": graph["body"]} if is_v1 and not is_bodyless else graph
    legacy_projection = (
        {
            "body": graph["body"],
            "parser_semantics_version": graph["parser_semantics_version"],
        }
        if is_v1 and not is_bodyless else graph
    )
    envelope = {
        "schema_version": 1,
        "metrics_semantics_version": 4 if is_canonical_v3 else (3 if is_canonical_v2 else (2 if is_v1 else 1)),
        "input": {
            "graph_schema_version": 1 if is_v1 else None,
            "graph_fingerprint": graph_fingerprint(graph) if is_v1 else _legacy_graph_fingerprint(graph),
            **({"legacy_body_fingerprint": _legacy_graph_fingerprint(legacy_body)}
               if is_v1 and not is_bodyless else {}),
        },
        # v1 formulas are temporarily isolated on the documented body adapter.
        "metrics": calculate_graph_metrics(
            graph if is_canonical_v2 else legacy_projection,
            canonical_mode=is_v1,
            legacy_resolution=not is_v1,
            canonical_objects=is_canonical_v2,
            canonical_calls=is_canonical_v2,
        ),
    }
    return _save_metrics_dto(envelope, output_path)
