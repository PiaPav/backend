"""File API for the complete legacy graph metrics implementation."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .logic.calculator import calculate_graph_metrics

__all__ = ["calculate_graph_metrics", "calculate_metrics", "load_graph"]


# Kept local deliberately: metrics accepts the legacy Graph DTO without
# depending on the parser package at runtime.
_CLASS_TYPES = {"class", "dataclass", "enum", "abstract"}


def _require_path(value: Path, name: str) -> Path:
    if not isinstance(value, Path):
        raise TypeError(f"{name} must be a pathlib.Path")
    return value


def load_graph(graph_path: Path) -> dict[str, Any]:
    """Load the unversioned legacy graph accepted by the migrated formulas."""
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
        version = data["schema_version"]
        if version != 0:
            raise ValueError(
                f"Unsupported graph schema_version: {version!r}; "
                "Graph DTO v1 is not supported"
            )
        raise ValueError("Versioned legacy graph is not supported")
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
    envelope = {
        "schema_version": 1,
        "metrics_semantics_version": 1,
        "input": {
            "graph_schema_version": None,
            "graph_fingerprint": _legacy_graph_fingerprint(graph),
        },
        "metrics": calculate_graph_metrics(graph),
    }
    target = output_path.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(envelope, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, target)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    return target
