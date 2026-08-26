
"""Public parser API."""

from __future__ import annotations

from pathlib import Path

from .analyzer import ProjectAnalyzer
from .serializer import save_graph

__all__ = ["starter", "save_graph"]


def starter(input_project: str | Path) -> dict:
    """Analyze a Python project and return its JSON-compatible graph."""
    return ProjectAnalyzer(input_project).analyze()
