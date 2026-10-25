"""The dependency.architecture v1 roots, classes and import occurrence projection."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from graph_dto import validate_graph_v1

from ..contract import aggregate_import_edge_id, graph_view_fingerprint, validate_graph_view_v1
from ..metrics_contract import PACKAGE_GROUPING
from ..registry import profile_metadata


def project_dependency_architecture_v1(source_graph: Mapping[str, Any]) -> dict[str, Any]:
    validate_graph_v1(source_graph)
    return _project_dependency_architecture_v1(source_graph)


def _project_dependency_architecture_v1(source_graph: Mapping[str, Any]) -> dict[str, Any]:
    if source_graph["schema_version"] != 1 or source_graph["parser_semantics_version"] != 7:
        raise ValueError("dependency.architecture v1 requires Graph DTO schema 1 / parser semantics 7")
    source_nodes = {node["id"]: node for node in source_graph["nodes"]}
    included = {identifier for identifier, node in source_nodes.items() if node["kind"] in {"file", "module", "class"}}
    nodes = []
    for node in source_graph["nodes"]:
        if node["id"] not in included: continue
        keys = ("id", "kind", "qualified_name", "path", "parent_id", "class_kind") if node["kind"] == "class" else ("id", "kind", "qualified_name", "path")
        nodes.append({key: deepcopy(node[key]) for key in keys})
    contains = [{key: deepcopy(edge[key]) for key in ("id", "kind", "source_id", "target_id")}
                for edge in source_graph["edges"] if edge["kind"] == "contains" and edge["source_id"] in included and edge["target_id"] in included and source_nodes[edge["target_id"]]["kind"] == "class"]
    references = [{key: deepcopy(reference[key]) for key in ("id", "importer_id", "kind", "module", "name", "alias", "level", "location", "resolution", "target_id", "candidate_ids")}
                  for reference in source_graph["import_references"]]
    counts = {status: 0 for status in ("exact", "external", "unresolved")}; pairs: dict[tuple[str, str], int] = {}
    for reference in references:
        counts[reference["resolution"]] += 1
        if reference["resolution"] == "exact":
            pair = (reference["importer_id"], reference["target_id"]); pairs[pair] = pairs.get(pair, 0) + 1
    imports = [{"id": aggregate_import_edge_id(source, target), "kind": "imports", "source_id": source, "target_id": target, "exact_occurrence_count": count}
               for (source, target), count in pairs.items()]
    view = {"artifact_kind": "graph_view", "view_schema_version": 1,
            "profile": {"id": "dependency.architecture", "version": 1},
            "source": {"graph_schema_version": source_graph["schema_version"], "parser_semantics_version": source_graph["parser_semantics_version"], "graph_fingerprint": source_graph["project"]["fingerprint"]},
            "completeness": profile_metadata("dependency.architecture", 1),
            "payload": {"nodes": sorted(nodes, key=lambda item: item["id"]), "edges": sorted(contains + imports, key=lambda item: item["id"]), "import_references": sorted(references, key=lambda item: item["id"]), "import_resolution_counts": counts, "package_grouping": deepcopy(PACKAGE_GROUPING)},
            "view_fingerprint": "0" * 64}
    view["view_fingerprint"] = graph_view_fingerprint(view); validate_graph_view_v1(view); return view


__all__ = ["project_dependency_architecture_v1"]
