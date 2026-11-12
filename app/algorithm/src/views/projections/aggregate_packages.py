"""aggregate.packages v2 compact quotient projection."""
from __future__ import annotations

from typing import Any, Mapping

from graph_dto import validate_graph_v1

from ..aggregate_packages_contract import (
    aggregate_package_edge_id, aggregate_package_id,
)
from ..registry import summary_profile_metadata
from ..summary_contract import graph_summary_fingerprint, validate_graph_summary_v1


def _package(path: str) -> str:
    return path.split("/", 1)[0] if "/" in path else "<root>"


def project_aggregate_packages_v2(source_graph: Mapping[str, Any]) -> dict[str, Any]:
    validate_graph_v1(source_graph)
    return _project_aggregate_packages_v2(source_graph)


def _project_aggregate_packages_v2(source_graph: Mapping[str, Any]) -> dict[str, Any]:
    if source_graph["schema_version"] != 1 or source_graph["parser_semantics_version"] != 7:
        raise ValueError("aggregate.packages v2 requires Graph DTO schema 1 / parser semantics 7")
    nodes = {node["id"]: node for node in source_graph["nodes"]}
    roots = {identifier: node for identifier, node in nodes.items() if node["parent_id"] is None}
    root_package = {identifier: _package(node["path"]) for identifier, node in roots.items()}
    labels = set(root_package.values())
    stats = {label: [0] * 9 for label in labels}
    for label in root_package.values():
        stats[label][0] += 1

    def owning_root(identifier: str) -> str:
        seen = set()
        while nodes[identifier]["parent_id"] is not None:
            if identifier in seen:
                raise ValueError("aggregate.packages ownership cycle")
            seen.add(identifier); identifier = nodes[identifier]["parent_id"]
        return identifier

    for node in nodes.values():
        if node["parent_id"] is None:
            continue
        label = root_package[owning_root(node["id"])]
        stats[label][1] += 1
        if node["kind"] == "class" and node["parent_id"] in roots:
            stats[label][2] += 1
            if node.get("class_kind") == "abstract":
                stats[label][3] += 1

    internal_pairs = {label: set() for label in labels}
    cross: dict[tuple[str, str], list[Any]] = {}
    for reference in source_graph["import_references"]:
        source_root = reference["importer_id"]
        source_label = root_package[source_root]
        status = reference["resolution"]
        if status == "external": stats[source_label][4] += 1
        elif status == "unresolved": stats[source_label][5] += 1
        elif status == "exact":
            target_root = reference["target_id"]
            target_label = root_package[target_root]
            if source_label == target_label:
                internal_pairs[source_label].add((source_root, target_root))
                stats[source_label][7] += 1
                if source_root == target_root: stats[source_label][8] += 1
            else:
                value = cross.setdefault((source_label, target_label), [set(), 0])
                value[0].add((source_root, target_root)); value[1] += 1
    for label in labels:
        stats[label][6] = len(internal_pairs[label])

    ordered_labels = sorted(labels, key=aggregate_package_id)
    indexes = {label: index for index, label in enumerate(ordered_labels)}
    packages = [[label, *stats[label]] for label in ordered_labels]
    edge_values = []
    for (source, target), (pairs, exact) in cross.items():
        edge_values.append((aggregate_package_edge_id(aggregate_package_id(source), aggregate_package_id(target)),
                            [indexes[source], indexes[target], len(pairs), exact]))
    imports = [row for _identifier, row in sorted(edge_values)]
    summary = {
        "artifact_kind": "graph_summary", "summary_schema_version": 1,
        "profile": {"id": "aggregate.packages", "version": 2},
        "source": {"graph_schema_version": 1, "parser_semantics_version": 7,
                   "graph_fingerprint": source_graph["project"]["fingerprint"]},
        "completeness": summary_profile_metadata("aggregate.packages", 2),
        "payload": {"graph_kind": "quotient", "wire_format": 2, "grouping_version": 1,
                    "packages": packages, "imports": imports},
        "summary_fingerprint": "0" * 64,
    }
    summary["summary_fingerprint"] = graph_summary_fingerprint(summary)
    validate_graph_summary_v1(summary)
    return summary


__all__ = ["project_aggregate_packages_v2"]
