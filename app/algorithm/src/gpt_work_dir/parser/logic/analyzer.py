"""Multi-pass project analysis orchestration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .calls import CallResolver
from .classifiers import classify_classes
from .definitions import collect_definitions
from .imports import collect_imports
from .project_index import ProjectIndex
from .serializer import GraphSerializer
from .validation import validate_graph


class ProjectAnalyzer:
    def __init__(self, root: str | Path) -> None:
        self.index = ProjectIndex(root)

    def analyze(self) -> dict[str, Any]:
        modules = self.index.discover()
        for module in modules:
            collect_imports(module, self.index)
            collect_definitions(module)
        classify_classes(modules)
        calls = CallResolver(modules)
        calls.resolve_all()
        graph = GraphSerializer(modules, calls).serialize()
        validate_graph(graph)
        return graph
