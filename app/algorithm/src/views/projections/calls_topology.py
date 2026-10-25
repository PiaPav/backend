"""The calls.topology v1 callable topology projection."""
from __future__ import annotations

from typing import Any, Mapping

from graph_dto import validate_graph_v1

from ..contract import graph_view_fingerprint, validate_graph_view_v1
from ..registry import profile_metadata


def project_calls_topology_v1(source_graph: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and project a semantics-v7 canonical graph."""
    validate_graph_v1(source_graph)
    return _project_calls_topology_v1(source_graph)


def _project_calls_topology_v1(source_graph: Mapping[str, Any]) -> dict[str, Any]:
    if source_graph["schema_version"] != 1 or source_graph["parser_semantics_version"] != 7:
        raise ValueError("calls.topology v1 requires Graph DTO schema 1 / parser semantics 7")

    by_id = {node["id"]: node for node in source_graph["nodes"]}
    selected = {identifier for identifier, node in by_id.items() if node["kind"] in {"function", "method"}}
    module_owners = sorted({
        callsite["caller_id"] for callsite in source_graph["callsites"]
        if by_id[callsite["caller_id"]]["kind"] in {"file", "module"}
    })
    selected.update(module_owners)
    for identifier in tuple(selected):
        current = identifier
        while by_id[current].get("parent_id") is not None:
            current = by_id[current]["parent_id"]
            selected.add(current)

    nodes = []
    for identifier in selected:
        source = by_id[identifier]
        keys = ("id", "kind", "qualified_name", "path") if source["kind"] in {"file", "module"} else (
            "id", "kind", "qualified_name", "parent_id", "path"
        )
        node = {key: source[key] for key in keys}
        if source["kind"] == "method" and source.get("synthetic") is True:
            node["synthetic"] = True
        nodes.append(node)

    edges = []
    for source in source_graph["edges"]:
        if source["kind"] == "contains" and source["source_id"] in selected and source["target_id"] in selected:
            edges.append({key: source[key] for key in ("id", "kind", "source_id", "target_id")})
        elif source["kind"] in {"calls", "awaits"}:
            edges.append({key: source[key] for key in ("id", "kind", "source_id", "target_id", "weight")})

    counts = {
        status: {"awaited": 0, "non_awaited": 0}
        for status in ("exact", "ambiguous", "external", "dynamic", "unresolved")
    }
    for callsite in source_graph["callsites"]:
        counts[callsite["resolution"]]["awaited" if callsite["awaited"] else "non_awaited"] += 1

    view: dict[str, Any] = {
        "artifact_kind": "graph_view", "view_schema_version": 1,
        "profile": {"id": "calls.topology", "version": 1},
        "source": {"graph_schema_version": 1, "parser_semantics_version": 7,
                   "graph_fingerprint": source_graph["project"]["fingerprint"]},
        "completeness": profile_metadata("calls.topology", 1),
        "payload": {"nodes": sorted(nodes, key=lambda item: item["id"]),
                    "edges": sorted(edges, key=lambda item: item["id"]),
                    "module_call_owner_ids": module_owners, "callsite_counts": counts},
        "view_fingerprint": "0" * 64,
    }
    view["view_fingerprint"] = graph_view_fingerprint(view)
    validate_graph_view_v1(view)
    return view


__all__ = ["project_calls_topology_v1"]
