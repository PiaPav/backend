"""Multi-pass project analysis orchestration."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from .calls import CallResolver
from .classifiers import classify_classes
from .definitions import collect_definitions
from .imports import collect_imports
from .project_index import ProjectIndex
from .relations import RelationResolver
from .serializer import GraphSerializer
from .validation import validate_graph

if TYPE_CHECKING:
    from .source_index import SourceIndexBuilder


class ProjectAnalyzer:
    def __init__(self, root: str | Path) -> None:
        self.index = ProjectIndex(root)

    def analyze(self) -> dict[str, Any]:
        graph, _ = self._analyze(source_index_builder=None)
        return graph

    def analyze_with_source_index(self) -> tuple[dict[str, Any], dict[str, Any]]:
        from .source_index import SourceIndexBuilder

        graph, source_index = self._analyze(SourceIndexBuilder(self.index.root))
        assert source_index is not None
        return graph, source_index

    def _analyze(
        self, source_index_builder: SourceIndexBuilder | None
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        modules = self.index.discover()
        for module in modules:
            collect_imports(module, self.index)
            on_node = (
                source_index_builder.start_module(module)
                if source_index_builder is not None
                else None
            )
            collect_definitions(module, on_node)
        RelationResolver(modules, self.index).resolve_all()
        classify_classes(modules)
        calls = CallResolver(modules, self.index)
        calls.resolve_all()
        graph = GraphSerializer(modules, calls).serialize()
        validate_graph(graph)
        source_index = (
            source_index_builder.build() if source_index_builder is not None else None
        )
        return graph, source_index
