"""The structure.declarations v1 whitelist projection."""
from __future__ import annotations

from typing import Any, Mapping

from graph_dto import validate_graph_v1

from ..contract import graph_view_fingerprint, validate_graph_view_v1
from ..registry import profile_metadata


def project_structure_declarations_v1(source_graph: Mapping[str, Any]) -> dict[str, Any]:
    """Project a validated semantics-v7 canonical graph without mutating it."""
    validate_graph_v1(source_graph)
    return _project_structure_declarations_v1(source_graph)


def _project_structure_declarations_v1(source_graph: Mapping[str, Any]) -> dict[str, Any]:
    """Project a source graph already validated by the public gateway."""
    if source_graph["schema_version"] != 1 or source_graph["parser_semantics_version"] != 7:
        raise ValueError("structure.declarations v1 requires Graph DTO schema 1 / parser semantics 7")

    nodes = []
    for source in source_graph["nodes"]:
        node = {key: source[key] for key in ("id", "kind", "qualified_name", "path")}
        node["parent_id"] = source.get("parent_id")
        if source["kind"] == "class":
            node["class_kind"] = source["class_kind"]
        if source["kind"] == "method" and source.get("synthetic") is True:
            node["synthetic"] = True
        nodes.append(node)
    edges = [
        {key: source[key] for key in ("id", "kind", "source_id", "target_id")}
        for source in source_graph["edges"] if source["kind"] == "contains"
    ]
    view: dict[str, Any] = {
        "artifact_kind": "graph_view",
        "view_schema_version": 1,
        "profile": {"id": "structure.declarations", "version": 1},
        "source": {
            "graph_schema_version": source_graph["schema_version"],
            "parser_semantics_version": source_graph["parser_semantics_version"],
            "graph_fingerprint": source_graph["project"]["fingerprint"],
        },
        "completeness": {
            key: list(value) if isinstance(value, list) else value
            for key, value in profile_metadata("structure.declarations", 1).items()
        },
        "payload": {
            "nodes": sorted(nodes, key=lambda item: item["id"]),
            "edges": sorted(edges, key=lambda item: item["id"]),
        },
        "view_fingerprint": "0" * 64,
    }
    view["view_fingerprint"] = graph_view_fingerprint(view)
    validate_graph_view_v1(view)
    return view


__all__ = ["project_structure_declarations_v1"]
