"""The objects.metrics_basis v1 object-metrics projection."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from graph_dto import validate_graph_v1

from ..contract import graph_view_fingerprint, validate_graph_view_v1
from ..registry import profile_metadata


def project_objects_metrics_basis_v1(source_graph: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and project a semantics-v7 canonical graph."""
    validate_graph_v1(source_graph)
    return _project_objects_metrics_basis_v1(source_graph)


def _project_objects_metrics_basis_v1(source_graph: Mapping[str, Any]) -> dict[str, Any]:
    if source_graph["schema_version"] != 1 or source_graph["parser_semantics_version"] != 7:
        raise ValueError("objects.metrics_basis v1 requires Graph DTO schema 1 / parser semantics 7")

    by_id = {node["id"]: node for node in source_graph["nodes"]}
    real_methods = {
        identifier for identifier, node in by_id.items()
        if node["kind"] == "method" and node.get("synthetic") is not True
    }
    selected = {
        identifier for identifier, node in by_id.items()
        if node["kind"] in {"class", "field", "method"}
    }
    for edge in source_graph["edges"]:
        if (edge["kind"] in {"calls", "awaits"} and edge["source_id"] in real_methods
                and by_id[edge["target_id"]]["kind"] == "function"):
            selected.add(edge["target_id"])
    for identifier in tuple(selected):
        current = identifier
        while by_id[current].get("parent_id") is not None:
            current = by_id[current]["parent_id"]
            selected.add(current)

    nodes = []
    for identifier in selected:
        source = by_id[identifier]
        if source["kind"] in {"file", "module"}:
            keys = ("id", "kind", "qualified_name", "path")
        else:
            keys = ("id", "kind", "qualified_name", "parent_id", "path")
        node = {key: source[key] for key in keys}
        if source["kind"] == "method":
            if source.get("synthetic") is True:
                node["synthetic"] = True
            else:
                node["complexity_facts"] = deepcopy(source["complexity_facts"])
        nodes.append(node)

    edges = []
    for source in source_graph["edges"]:
        kind = source["kind"]
        retain = (
            kind in {"inherits", "field_type"}
            or (kind == "contains" and source["source_id"] in selected and source["target_id"] in selected)
            or (kind == "accesses_field" and source["source_id"] in real_methods)
            or (kind in {"calls", "awaits"} and source["source_id"] in real_methods)
        )
        if retain:
            keys = ("id", "kind", "source_id", "target_id", "weight") if kind in {"calls", "awaits"} else ("id", "kind", "source_id", "target_id")
            edges.append({key: source[key] for key in keys})

    references = [{
        "id": ref["id"], "owner_id": ref["owner_id"], "role": ref["role"],
        "expression": ref["expression"],
        "location": {key: ref["location"][key] for key in ("path", "line", "column")},
        "resolution": ref["resolution"], "target_id": ref.get("target_id"),
        "candidate_ids": deepcopy(ref.get("candidate_ids", [])),
    } for ref in source_graph["type_references"]]
    view = {
        "artifact_kind": "graph_view", "view_schema_version": 1,
        "profile": {"id": "objects.metrics_basis", "version": 1},
        "source": {"graph_schema_version": 1, "parser_semantics_version": 7,
                   "graph_fingerprint": source_graph["project"]["fingerprint"]},
        "completeness": profile_metadata("objects.metrics_basis", 1),
        "payload": {"nodes": sorted(nodes, key=lambda item: item["id"]),
                    "edges": sorted(edges, key=lambda item: item["id"]),
                    "type_references": sorted(references, key=lambda item: item["id"])},
        "view_fingerprint": "0" * 64,
    }
    view["view_fingerprint"] = graph_view_fingerprint(view)
    validate_graph_view_v1(view)
    return view


__all__ = ["project_objects_metrics_basis_v1"]
