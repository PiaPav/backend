
"""Public parser API."""

from __future__ import annotations

from pathlib import Path

from .analyzer import ProjectAnalyzer
from .serializer import save_graph
from .source_index import save_source_index

__all__ = [
    "starter",
    "starter_with_source_index",
    "save_graph",
    "save_source_index",
]


def starter(input_project: str | Path) -> dict:
    """Analyze a Python project and return its JSON-compatible graph."""
    return ProjectAnalyzer(input_project).analyze()


def starter_with_source_index(input_project: str | Path) -> tuple[dict, dict]:
    """Analyze a project and return its unchanged graph plus source index."""
    graph, source_index = ProjectAnalyzer(input_project).analyze_with_source_index()
    return graph, source_index
