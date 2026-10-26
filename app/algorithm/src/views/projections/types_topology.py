"""The types.topology v1 class and field type projection."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from graph_dto import validate_graph_v1

from ..contract import graph_view_fingerprint, validate_graph_view_v1
from ..registry import profile_metadata


def project_types_topology_v1(source_graph: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and project a semantics-v7 canonical graph."""
    validate_graph_v1(source_graph)
    return _project_types_topology_v1(source_graph)


def _project_types_topology_v1(source_graph: Mapping[str, Any]) -> dict[str, Any]:
    if source_graph["schema_version"] != 1 or source_graph["parser_semantics_version"] != 7:
        raise ValueError("types.topology v1 requires Graph DTO schema 1 / parser semantics 7")

    by_id = {node["id"]: node for node in source_graph["nodes"]}
    selected = {
        identifier for identifier, node in by_id.items()
        if node["kind"] in {"class", "field"}
    }
    for identifier in tuple(selected):
        current = identifier
        while by_id[current].get("parent_id") is not None:
            current = by_id[current]["parent_id"]
            selected.add(current)

    nodes = []
    for identifier in selected:
        source = by_id[identifier]
        keys = (("id", "kind", "qualified_name", "path")
                if source["kind"] in {"file", "module"}
                else ("id", "kind", "qualified_name", "parent_id", "path"))
        nodes.append({key: source[key] for key in keys})

    edges = [
        {key: edge[key] for key in ("id", "kind", "source_id", "target_id")}
        for edge in source_graph["edges"]
        if edge["kind"] in {"inherits", "field_type"}
        or (edge["kind"] == "contains"
            and edge["source_id"] in selected and edge["target_id"] in selected)
    ]
    references = sorted(({
        "id": reference["id"],
        "owner_id": reference["owner_id"],
        "role": reference["role"],
        "expression": reference["expression"],
        "location": {
            "path": reference["location"]["path"],
            "line": reference["location"]["line"],
            "column": reference["location"]["column"],
        },
        "resolution": reference["resolution"],
        "target_id": reference.get("target_id", None),
        "candidate_ids": deepcopy(reference.get("candidate_ids", [])),
    } for reference in source_graph["type_references"]), key=lambda item: item["id"])
    view: dict[str, Any] = {
        "artifact_kind": "graph_view", "view_schema_version": 1,
        "profile": {"id": "types.topology", "version": 1},
        "source": {"graph_schema_version": 1, "parser_semantics_version": 7,
                   "graph_fingerprint": source_graph["project"]["fingerprint"]},
        "completeness": profile_metadata("types.topology", 1),
        "payload": {"nodes": sorted(nodes, key=lambda item: item["id"]),
                    "edges": sorted(edges, key=lambda item: item["id"]),
                    "type_references": references},
        "view_fingerprint": "0" * 64,
    }
    view["view_fingerprint"] = graph_view_fingerprint(view)
    validate_graph_view_v1(view)
    return view


__all__ = ["project_types_topology_v1"]
