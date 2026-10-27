"""Public API for versioned data views."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from graph_dto import validate_graph_v1

from .contract import (
    aggregate_import_edge_id, graph_view_fingerprint, serialize_graph_view,
    validate_graph_view_v1,
)
from .summary_contract import graph_summary_fingerprint, serialize_graph_summary, validate_graph_summary_v1
from .metrics_contract import metrics_view_fingerprint, serialize_metrics_view, validate_metrics_source_v1, validate_metrics_view_v1
from .projections.metrics_architecture import _project_metrics_architecture_v1
from .projections.metrics_overview import _project_metrics_overview_v1
from .projections.metrics_quality import _project_metrics_quality_v1
from .projections.inventory_minimal import _project_inventory_minimal_v1
from .projections.dependency_files import _project_dependency_files_v1
from .projections.dependency_architecture import _project_dependency_architecture_v1
from .projections.structure_declarations import _project_structure_declarations_v1
from .projections.calls_topology import _project_calls_topology_v1
from .projections.calls_detailed import _project_calls_detailed_v1
from .projections.types_topology import _project_types_topology_v1
from .projections.objects_metrics_basis import _project_objects_metrics_basis_v1
from .registry import profile_metadata, select_graph_profile, summary_profile_metadata
from .registry import metrics_profile_metadata


def materialize_metrics_profile(
    source_metrics: Mapping[str, Any], *, profile_id: str, profile_version: int
) -> dict[str, Any]:
    """Materialize an explicitly selected Metrics profile."""
    validate_metrics_source_v1(source_metrics)
    metrics_profile_metadata(profile_id, profile_version)
    if profile_id == "metrics.overview":
        return _project_metrics_overview_v1(source_metrics)
    if profile_id == "metrics.architecture":
        return _project_metrics_architecture_v1(source_metrics)
    if profile_id == "metrics.quality":
        return _project_metrics_quality_v1(source_metrics)
    raise ValueError(f"Unsupported metrics profile {profile_id!r}")


def project_metrics_view(
    source_metrics: Mapping[str, Any], *, profile_id: str, profile_version: int
) -> dict[str, Any]:
    """Project an exact Metrics View profile without fallback."""
    return materialize_metrics_profile(source_metrics, profile_id=profile_id, profile_version=profile_version)


def materialize_graph_profile(
    source_graph: Mapping[str, Any], *, profile_id: str, profile_version: int
) -> dict[str, Any]:
    """Materialize an explicitly selected initial graph profile."""
    validate_graph_v1(source_graph)
    profile_kind = select_graph_profile(profile_id, profile_version)
    if profile_id == "structure.declarations" and profile_kind == "graph_view":
        return _project_structure_declarations_v1(source_graph)
    if profile_id == "dependency.files" and profile_kind == "graph_view":
        return _project_dependency_files_v1(source_graph)
    if profile_id == "dependency.architecture" and profile_kind == "graph_view":
        return _project_dependency_architecture_v1(source_graph)
    if profile_id == "calls.topology" and profile_kind == "graph_view":
        return _project_calls_topology_v1(source_graph)
    if profile_id == "calls.detailed" and profile_kind == "graph_view":
        return _project_calls_detailed_v1(source_graph)
    if profile_id == "types.topology" and profile_kind == "graph_view":
        return _project_types_topology_v1(source_graph)
    if profile_id == "objects.metrics_basis" and profile_kind == "graph_view":
        return _project_objects_metrics_basis_v1(source_graph)
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
    if profile_id == "structure.declarations":
        return _project_structure_declarations_v1(source_graph)
    if profile_id == "dependency.files":
        return _project_dependency_files_v1(source_graph)
    if profile_id == "dependency.architecture":
        return _project_dependency_architecture_v1(source_graph)
    if profile_id == "calls.topology":
        return _project_calls_topology_v1(source_graph)
    if profile_id == "calls.detailed":
        return _project_calls_detailed_v1(source_graph)
    if profile_id == "types.topology":
        return _project_types_topology_v1(source_graph)
    if profile_id == "objects.metrics_basis":
        return _project_objects_metrics_basis_v1(source_graph)
    raise ValueError(f"Unsupported graph view profile {profile_id!r}")


def project_graph_summary(
    source_graph: Mapping[str, Any], *, profile_id: str, profile_version: int
) -> dict[str, Any]:
    """Project an explicitly selected Graph Summary profile."""
    validate_graph_v1(source_graph)
    summary_profile_metadata(profile_id, profile_version)
    return _project_inventory_minimal_v1(source_graph)


__all__ = [
    "aggregate_import_edge_id", "graph_summary_fingerprint", "graph_view_fingerprint",
    "materialize_graph_profile",
    "materialize_metrics_profile", "metrics_view_fingerprint", "project_metrics_view",
    "project_graph_summary", "project_graph_view", "serialize_graph_summary",
    "serialize_graph_view", "validate_graph_summary_v1", "validate_graph_view_v1",
    "serialize_metrics_view", "validate_metrics_source_v1", "validate_metrics_view_v1",
]
