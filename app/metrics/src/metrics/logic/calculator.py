"""Calculate canonical project metrics from Graph DTO v1 semantics 6/7."""
from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from graph_dto import validate_graph_v1

from .architecture import calculate_architecture_metrics
from .call_graph import _calculate_call_graph_metrics
from .graph_algorithms import strong_components as _strong_components
from .object_metrics import _calculate_canonical_object_metrics
from .projections import MetricsGraphProjection
from .quality import _calculate_quality_metrics


def validate_metrics_graph(graph: Mapping[str, Any]) -> None:
    """Apply the complete canonical-only in-memory Metrics input contract."""
    if not isinstance(graph, Mapping):
        validate_graph_v1(graph)
    if type(graph.get("schema_version")) is not int or graph.get("schema_version") != 1:
        raise ValueError(f"Unsupported graph schema_version: {graph.get('schema_version')!r}")
    semantics = graph.get("parser_semantics_version")
    if type(semantics) is not int or semantics not in {6, 7}:
        raise ValueError(
            f"Unsupported parser_semantics_version: {semantics!r}; metrics supports 6 and 7 only; "
            "regenerate with parser.parse_project"
        )
    validate_graph_v1(graph)


def _weak_components(nodes: set[str], edges: set[tuple[str, str]]) -> list[set[str]]:
    neighbors = {node: set() for node in nodes}
    for source, target in edges:
        neighbors[source].add(target); neighbors[target].add(source)
    components = []
    unseen = set(nodes)
    while unseen:
        pending = [unseen.pop()]; component = set()
        while pending:
            node = pending.pop(); component.add(node)
            discovered = neighbors[node] & unseen; unseen -= discovered; pending.extend(discovered)
        components.append(component)
    return components


def _degree_peak(degrees: Mapping[str, int]) -> dict[str, Any]:
    maximum = max(degrees.values(), default=0)
    return {"degree": maximum, "files": sorted(node for node, degree in degrees.items() if degree == maximum)}


def _canonical_size(projection: MetricsGraphProjection) -> dict[str, int]:
    nodes = projection.nodes_by_id; by_kind = projection.node_ids_by_kind
    roots = by_kind.get("file", frozenset()) | by_kind.get("module", frozenset())
    directories: set[str] = set()
    for identifier in roots:
        parts = str(nodes[identifier].get("path") or "").split("/")[:-1]
        directories.update("/".join(parts[:index]) for index in range(1, len(parts) + 1))
    classes = by_kind.get("class", frozenset())
    return {
        "directories": len(directories), "files": len(roots), "classes": len(classes),
        "abstract_classes": sum(nodes[item].get("class_kind") == "abstract" for item in classes),
        "dataclasses": sum(nodes[item].get("class_kind") == "dataclass" for item in classes),
        "functions": len(by_kind.get("function", frozenset())),
        "methods": sum(nodes[item].get("synthetic") is not True for item in by_kind.get("method", frozenset())),
        "fields": len(by_kind.get("field", frozenset())), "constants": len(by_kind.get("constant", frozenset())),
    }


def calculate_graph_metrics(graph: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and calculate metrics from one canonical immutable projection."""
    validate_metrics_graph(graph)
    return _calculate_graph_metrics(MetricsGraphProjection.from_graph(graph))


def _calculate_graph_metrics(projection: MetricsGraphProjection) -> dict[str, Any]:
    file_graph = projection.directed_file_import_graph
    nodes = set(file_graph.nodes); edges = set(file_graph.edges)
    facts = projection.owner_structural_facts_by_id
    roots = projection.node_ids_by_kind.get("file", frozenset()) | projection.node_ids_by_kind.get("module", frozenset())
    callable_ids = projection.node_ids_by_kind.get("function", frozenset()) | {
        identifier for identifier in projection.node_ids_by_kind.get("method", frozenset())
        if projection.nodes_by_id[identifier].get("synthetic") is not True
    }
    module_calls = sum(int(facts[item]["call_occurrences"]) for item in roots)
    callable_calls = sum(int(facts[item]["call_occurrences"]) for item in callable_ids)
    calls = module_calls + callable_calls
    local_imports = sum(int(facts[item]["direct_import_occurrences"]["project_local"]) for item in roots)
    external_imports = sum(int(facts[item]["direct_import_occurrences"]["non_project"]) for item in roots)
    call_owners = len(callable_ids) + sum(facts[item]["call_occurrences"] > 0 for item in roots)
    fan_in = dict.fromkeys(nodes, 0); fan_out = dict.fromkeys(nodes, 0)
    for source, target in edges: fan_out[source] += 1; fan_in[target] += 1
    cyclic = sorted(sorted(component) for component in _strong_components(nodes, edges) if len(component) > 1)
    count = len(nodes); denominator = count * (count - 1)
    classes = len(projection.node_ids_by_kind.get("class", frozenset()))
    methods = sum(projection.nodes_by_id[item].get("synthetic") is not True for item in projection.node_ids_by_kind.get("method", frozenset()))
    return {
        "size": _canonical_size(projection),
        "activity": {
            "calls": calls, "local_imports": local_imports, "external_imports": external_imports,
            "average_calls_per_callable": round(callable_calls / len(callable_ids), 4) if callable_ids else 0.0,
            "average_calls_per_call_owner": round(calls / call_owners, 4) if call_owners else 0.0,
            "average_methods_per_class": round(methods / classes, 4) if classes else 0.0,
        },
        "dependency_graph": {
            "nodes": count, "edges": len(edges), "density": round(len(edges) / denominator, 4) if denominator else 0.0,
            "average_fan_in": round(len(edges) / count, 4) if count else 0.0,
            "average_fan_out": round(len(edges) / count, 4) if count else 0.0,
            "weakly_connected_components": len(_weak_components(nodes, edges)),
            "isolated_files": sorted(node for node in nodes if fan_in[node] == fan_out[node] == 0),
            "cyclic_components": cyclic, "highest_fan_in": _degree_peak(fan_in), "highest_fan_out": _degree_peak(fan_out),
        },
        "architecture": calculate_architecture_metrics(projection),
        "code_quality": _calculate_quality_metrics(projection),
        "object_oriented": _calculate_canonical_object_metrics(projection),
        "call_graph": _calculate_call_graph_metrics(projection),
    }


def format_graph_metrics(metrics: Mapping[str, Any]) -> str:
    return json.dumps(metrics, ensure_ascii=False, indent=2)
