"""File API and compatibility facade for the legacy project parser."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .logic.analyzer import ProjectAnalyzer

__all__ = ["parse_project", "starter"]


def starter(input_project: str | Path) -> dict:
    """Analyze a Python project and return its JSON-compatible graph."""
    return ProjectAnalyzer(input_project).analyze()


def _require_path(value: Path, name: str) -> Path:
    if not isinstance(value, Path):
        raise TypeError(f"{name} must be a pathlib.Path")
    return value


def parse_project(source_path: Path, output_path: Path) -> Path:
    """Analyze ``source_path`` and atomically save its legacy graph.

    ``starter`` deliberately remains available for existing in-memory clients.
    The file representation is canonical JSON only; it does not alter the
    graph returned by :class:`ProjectAnalyzer`.
    """
    source_path = _require_path(source_path, "source_path")
    output_path = _require_path(output_path, "output_path")
    graph = starter(source_path)
    target = output_path.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(graph, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, target)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    return target
