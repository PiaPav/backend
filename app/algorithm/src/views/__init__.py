"""Public API for versioned data views."""
from __future__ import annotations

from typing import Any, Mapping

from graph_dto import validate_graph_v1

from .contract import graph_view_fingerprint, serialize_graph_view, validate_graph_view_v1
from .projections.structure_declarations import _project_structure_declarations_v1
from .registry import profile_metadata


def project_graph_view(
    source_graph: Mapping[str, Any], *, profile_id: str, profile_version: int
) -> dict[str, Any]:
    """Project an explicitly selected profile; no latest/default fallback exists."""
    validate_graph_v1(source_graph)
    profile_metadata(profile_id, profile_version)
    return _project_structure_declarations_v1(source_graph)


__all__ = [
    "graph_view_fingerprint", "project_graph_view", "serialize_graph_view",
    "validate_graph_view_v1",
]
