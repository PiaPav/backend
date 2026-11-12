"""File API and compatibility facade for the legacy project parser."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .logic.analyzer import ProjectAnalyzer
from .graph_v1 import build_graph_v1

__all__ = ["parse_project", "parse_project_with_source_index", "starter"]


def starter(input_project: str | Path) -> dict:
    """Analyze a Python project and return its JSON-compatible graph."""
    return ProjectAnalyzer(input_project).analyze()


def _require_path(value: Path, name: str) -> Path:
    if not isinstance(value, Path):
        raise TypeError(f"{name} must be a pathlib.Path")
    return value


def _save_json(value: object, output_path: Path) -> Path:
    target = output_path.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, target)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    return target


def parse_project(source_path: Path, output_path: Path) -> Path:
    """Analyze ``source_path`` and atomically save its canonical Graph DTO.

    ``starter`` deliberately remains available for existing in-memory clients.
    The file representation is canonical JSON only; it does not alter the
    graph returned by :class:`ProjectAnalyzer`.
    """
    source_path = _require_path(source_path, "source_path")
    output_path = _require_path(output_path, "output_path")
    analyzer = ProjectAnalyzer(source_path)
    analyzer.analyze()
    graph = build_graph_v1(analyzer.index)
    return _save_json(graph, output_path)


def parse_project_with_source_index(
    source_path: Path,
    graph_output_path: Path,
    source_index_output_path: Path,
) -> tuple[Path, Path]:
    """Analyze a project and atomically save its Graph DTO and source index.

    The source index is generated during the same definition pass as the graph,
    so its byte spans and project fingerprint describe the exact analyzed
    sources.  Each artifact is written atomically to its own target.
    """
    source_path = _require_path(source_path, "source_path")
    graph_output_path = _require_path(graph_output_path, "graph_output_path")
    source_index_output_path = _require_path(
        source_index_output_path, "source_index_output_path"
    )
    if graph_output_path.expanduser().resolve() == source_index_output_path.expanduser().resolve():
        raise ValueError("graph and source index output paths must differ")
    analyzer = ProjectAnalyzer(source_path)
    _, source_index = analyzer.analyze_with_source_index()
    graph = build_graph_v1(analyzer.index)
    graph_path = _save_json(graph, graph_output_path)
    index_path = _save_json(source_index, source_index_output_path)
    return graph_path, index_path
