"""Public API for versioned data views."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from graph_dto import validate_graph_v1

from .contract import graph_view_fingerprint, serialize_graph_view, validate_graph_view_v1
from .summary_contract import graph_summary_fingerprint, serialize_graph_summary, validate_graph_summary_v1
from .projections.inventory_minimal import _project_inventory_minimal_v1
from .projections.structure_declarations import _project_structure_declarations_v1
from .registry import profile_metadata, select_graph_profile, summary_profile_metadata


def materialize_graph_profile(
    source_graph: Mapping[str, Any], *, profile_id: str, profile_version: int
) -> dict[str, Any]:
    """Materialize an explicitly selected initial graph profile."""
    validate_graph_v1(source_graph)
    profile_kind = select_graph_profile(profile_id, profile_version)
    if profile_id == "structure.declarations" and profile_kind == "graph_view":
        return _project_structure_declarations_v1(source_graph)
    if profile_id == "inventory.minimal" and profile_kind == "graph_summary":
        return _project_inventory_minimal_v1(source_graph)
    if profile_id == "canonical.full" and profile_kind == "canonical":
        if source_graph["schema_version"] != 1 or source_graph["parser_semantics_version"] != 7:
            raise ValueError("canonical.full v1 requires Graph DTO schema 1 / parser semantics 7")
        return deepcopy(source_graph)
    raise ValueError(f"Unsupported graph profile dispatch {profile_id!r}/{profile_kind!r}")


def project_graph_view(
    source_graph: Mapping[str, Any], *, profile_id: str, profile_version: int
) -> dict[str, Any]:
    """Project an explicitly selected profile; no latest/default fallback exists."""
    validate_graph_v1(source_graph)
    profile_metadata(profile_id, profile_version)
    return _project_structure_declarations_v1(source_graph)


def project_graph_summary(
    source_graph: Mapping[str, Any], *, profile_id: str, profile_version: int
) -> dict[str, Any]:
    """Project an explicitly selected Graph Summary profile."""
    validate_graph_v1(source_graph)
    summary_profile_metadata(profile_id, profile_version)
    return _project_inventory_minimal_v1(source_graph)


__all__ = [
    "graph_summary_fingerprint", "graph_view_fingerprint", "materialize_graph_profile",
    "project_graph_summary", "project_graph_view", "serialize_graph_summary",
    "serialize_graph_view", "validate_graph_summary_v1", "validate_graph_view_v1",
]
