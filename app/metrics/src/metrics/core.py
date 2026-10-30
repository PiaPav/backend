"""File API for canonical Graph DTO metrics."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from graph_dto import graph_fingerprint, validate_graph_v1

from .logic.calculator import calculate_graph_metrics
from .logic.serialization import _save_metrics_dto

__all__ = ["calculate_graph_metrics", "calculate_metrics", "load_graph"]


def _require_path(value: Path, name: str) -> Path:
    if not isinstance(value, Path):
        raise TypeError(f"{name} must be a pathlib.Path")
    return value


def load_graph(graph_path: Path) -> dict[str, Any]:
    """Load a Graph DTO accepted by the canonical metrics contract."""
    path = _require_path(graph_path, "graph_path").expanduser().resolve()
    return _load_graph_bytes(path.read_bytes())


def _load_graph_bytes(raw: bytes) -> dict[str, Any]:
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        message = exc.msg if isinstance(exc, json.JSONDecodeError) else str(exc)
        raise ValueError(f"Invalid graph JSON: {message}") from exc
    if not isinstance(data, dict):
        raise ValueError("Graph root must be a JSON object")
    if "schema_version" not in data:
        raise ValueError(
            "Unversioned graphs are no longer supported; regenerate with parser.parse_project"
        )
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ValueError(f"Unsupported graph schema_version: {data['schema_version']!r}")
    semantics = data.get("parser_semantics_version")
    if type(semantics) is not int or semantics not in {6, 7}:
        raise ValueError(
            f"Unsupported parser_semantics_version: {semantics!r}; metrics supports 6 and 7 only; "
            "regenerate with parser.parse_project"
        )
    validate_graph_v1(data)
    return data


def calculate_metrics(graph_path: Path, output_path: Path) -> Path:
    """Calculate and atomically persist deterministic Metrics DTO v4."""
    graph_path = _require_path(graph_path, "graph_path")
    output_path = _require_path(output_path, "output_path")
    graph = _load_graph_bytes(graph_path.expanduser().resolve().read_bytes())
    envelope = {
        "schema_version": 1,
        "metrics_semantics_version": 4,
        "input": {
            "graph_schema_version": 1,
            "graph_fingerprint": graph_fingerprint(graph),
        },
        "metrics": calculate_graph_metrics(graph),
    }
    return _save_metrics_dto(envelope, output_path)
