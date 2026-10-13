"""Serialize graph metrics for storage and compact LLM input."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_TABLE_COLUMNS = "$columns"
_TABLE_ROWS = "$rows"


def _json_size(value: Any) -> int:
    return len(
        json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )


def save_graph_metrics(
    metrics: Mapping[str, Any], output_path: str | Path
) -> Path:
    """Write the complete, human-readable metrics JSON and return its path."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path.resolve()


def compact_graph_metrics(metrics: Mapping[str, Any]) -> dict[str, Any]:
    """Return a lossless, LLM-friendly representation of graph metrics.

    Whitespace is removed when the result is written. Repeated homogeneous
    objects are represented as ``$columns`` and ``$rows`` when that encoding is
    smaller than regular JSON. Metric values, including ``null``, zeroes and
    empty collections, are retained.
    """
    return dict(_compact_value(dict(metrics)))


def _compact_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _compact_value(item) for key, item in value.items()}
    if not isinstance(value, list):
        return value

    regular = [_compact_value(item) for item in value]
    if len(value) < 2 or not all(isinstance(item, Mapping) for item in value):
        return regular

    columns = list(value[0])
    if any(set(item) != set(columns) for item in value[1:]):
        return regular

    table = {
        _TABLE_COLUMNS: columns,
        _TABLE_ROWS: [
            [_compact_value(item[column]) for column in columns] for item in value
        ],
    }
    return table if _json_size(table) < _json_size(regular) else regular


def restore_graph_metrics(compact_metrics: Mapping[str, Any]) -> dict[str, Any]:
    """Restore metrics produced by :func:`compact_graph_metrics`."""
    restored = _restore_value(dict(compact_metrics))
    if not isinstance(restored, dict):
        raise ValueError("The restored metrics root must be a JSON object")
    return restored


def _restore_value(value: Any) -> Any:
    if isinstance(value, list):
        return [_restore_value(item) for item in value]
    if not isinstance(value, Mapping):
        return value

    if set(value) == {_TABLE_COLUMNS, _TABLE_ROWS}:
        columns = value[_TABLE_COLUMNS]
        rows = value[_TABLE_ROWS]
        if isinstance(columns, list) and isinstance(rows, list):
            result = []
            for row in rows:
                if not isinstance(row, list) or len(row) != len(columns):
                    raise ValueError("Invalid compact metrics table")
                result.append(
                    {
                        str(column): _restore_value(item)
                        for column, item in zip(columns, row, strict=True)
                    }
                )
            return result

    return {str(key): _restore_value(item) for key, item in value.items()}


def save_compact_graph_metrics(
    metrics: Mapping[str, Any], output_path: str | Path
) -> Path:
    """Write compact metrics JSON suitable for inclusion in an LLM prompt."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            compact_graph_metrics(metrics),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    return path.resolve()
