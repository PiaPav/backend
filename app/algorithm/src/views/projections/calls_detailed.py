"""The calls.detailed v1 lossless call-analysis projection."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from graph_dto import validate_graph_v1

from ..contract import graph_view_fingerprint, validate_graph_view_v1
from ..registry import profile_metadata


def project_calls_detailed_v1(source_graph: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and project a semantics-v7 canonical graph."""
    validate_graph_v1(source_graph)
    return _project_calls_detailed_v1(source_graph)


def _project_calls_detailed_v1(source_graph: Mapping[str, Any]) -> dict[str, Any]:
    if source_graph["schema_version"] != 1 or source_graph["parser_semantics_version"] != 7:
        raise ValueError("calls.detailed v1 requires Graph DTO schema 1 / parser semantics 7")

    by_id = {node["id"]: node for node in source_graph["nodes"]}
    selected = {
        identifier for identifier, node in by_id.items()
        if node["kind"] in {"file", "module", "function", "method"}
    }
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
        node = {key: deepcopy(source[key]) for key in keys}
        if source["kind"] in {"function", "method"}:
            if source.get("synthetic") is True:
                node["synthetic"] = True
            else:
                node["complexity_facts"] = deepcopy(source["complexity_facts"])
        nodes.append(node)

    edges = []
    for source in source_graph["edges"]:
        if source["kind"] == "contains" and source["source_id"] in selected and source["target_id"] in selected:
            edges.append({key: source[key] for key in ("id", "kind", "source_id", "target_id")})
        elif source["kind"] in {"calls", "awaits"}:
            edges.append({key: source[key] for key in ("id", "kind", "source_id", "target_id", "weight")})

    callsite_keys = (
        "id", "caller_id", "expression", "location", "syntactic_depth",
        "resolution", "target_id", "candidate_ids", "awaited",
    )
    callsites = sorted(
        ({key: deepcopy(source[key]) for key in callsite_keys} for source in source_graph["callsites"]),
        key=lambda item: item["id"],
    )
    module_owners = sorted({
        callsite["caller_id"] for callsite in callsites
        if by_id[callsite["caller_id"]]["kind"] in {"file", "module"}
    })
    fact_owners = {
        identifier for identifier in selected
        if by_id[identifier]["kind"] in {"file", "module"}
        or (by_id[identifier]["kind"] in {"function", "method"}
            and by_id[identifier].get("synthetic") is not True)
    }
    source_facts = {fact["owner_id"]: fact for fact in source_graph["owner_structural_facts"]}
    owner_facts = [
        {"owner_id": identifier, "call_occurrences": source_facts[identifier]["call_occurrences"]}
        for identifier in sorted(fact_owners)
    ]
    view: dict[str, Any] = {
        "artifact_kind": "graph_view", "view_schema_version": 1,
        "profile": {"id": "calls.detailed", "version": 1},
        "source": {"graph_schema_version": 1, "parser_semantics_version": 7,
                   "graph_fingerprint": source_graph["project"]["fingerprint"]},
        "completeness": profile_metadata("calls.detailed", 1),
        "payload": {"nodes": sorted(nodes, key=lambda item: item["id"]),
                    "edges": sorted(edges, key=lambda item: item["id"]),
                    "callsites": callsites, "module_call_owner_ids": module_owners,
                    "owner_structural_facts": owner_facts},
        "view_fingerprint": "0" * 64,
    }
    view["view_fingerprint"] = graph_view_fingerprint(view)
    validate_graph_view_v1(view)
    return view


__all__ = ["project_calls_detailed_v1"]
