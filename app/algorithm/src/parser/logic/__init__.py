"""Static Python project analysis logic."""

from pathlib import Path

from .analyzer import ProjectAnalyzer
from .serializer import save_graph


def starter(input_project: str | Path) -> dict:
    """Analyze a Python project without loading optional source-index support."""
    return ProjectAnalyzer(input_project).analyze()


def starter_with_source_index(input_project: str | Path) -> tuple[dict, dict]:
    """Compatibility wrapper that loads source-index support on demand."""
    from .main import starter_with_source_index as implementation

    return implementation(input_project)


def save_source_index(*args: object, **kwargs: object) -> object:
    """Compatibility wrapper that loads source-index serialization on demand."""
    from .source_index import save_source_index as implementation

    return implementation(*args, **kwargs)

__all__ = ["starter", "starter_with_source_index", "save_graph", "save_source_index"]
