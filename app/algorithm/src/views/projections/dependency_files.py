"""The dependency.files v1 exact-import topology projection."""
from __future__ import annotations

from typing import Any, Mapping

from graph_dto import validate_graph_v1

from ..contract import (
    aggregate_import_edge_id,
    graph_view_fingerprint,
    validate_graph_view_v1,
)
from ..registry import profile_metadata


def project_dependency_files_v1(source_graph: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and project a semantics-v7 canonical graph."""
    validate_graph_v1(source_graph)
    return _project_dependency_files_v1(source_graph)


def _project_dependency_files_v1(source_graph: Mapping[str, Any]) -> dict[str, Any]:
    """Project a source graph already validated by the public gateway."""
    if source_graph["schema_version"] != 1 or source_graph["parser_semantics_version"] != 7:
        raise ValueError("dependency.files v1 requires Graph DTO schema 1 / parser semantics 7")

    nodes = [
        {key: source[key] for key in ("id", "kind", "qualified_name", "path")}
        for source in source_graph["nodes"] if source["kind"] in {"file", "module"}
    ]
    counts = {"exact": 0, "external": 0, "unresolved": 0}
    pairs: dict[tuple[str, str], int] = {}
    for reference in source_graph["import_references"]:
        resolution = reference["resolution"]
        counts[resolution] += 1
        if resolution == "exact":
            pair = (reference["importer_id"], reference["target_id"])
            pairs[pair] = pairs.get(pair, 0) + 1
    edges = [
        {
            "id": aggregate_import_edge_id(source_id, target_id),
            "kind": "imports",
            "source_id": source_id,
            "target_id": target_id,
            "exact_occurrence_count": count,
        }
        for (source_id, target_id), count in pairs.items()
    ]
    view: dict[str, Any] = {
        "artifact_kind": "graph_view",
        "view_schema_version": 1,
        "profile": {"id": "dependency.files", "version": 1},
        "source": {
            "graph_schema_version": source_graph["schema_version"],
            "parser_semantics_version": source_graph["parser_semantics_version"],
            "graph_fingerprint": source_graph["project"]["fingerprint"],
        },
        "completeness": profile_metadata("dependency.files", 1),
        "payload": {
            "nodes": sorted(nodes, key=lambda item: item["id"]),
            "edges": sorted(edges, key=lambda item: item["id"]),
            "import_resolution_counts": counts,
        },
        "view_fingerprint": "0" * 64,
    }
    view["view_fingerprint"] = graph_view_fingerprint(view)
    validate_graph_view_v1(view)
    return view


__all__ = ["project_dependency_files_v1"]
