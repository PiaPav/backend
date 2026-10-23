"""Calculate project-size and file-dependency metrics from a parser graph."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

from .architecture import calculate_architecture_metrics
from .call_graph import calculate_call_graph_metrics
from .object_metrics import (
    _calculate_canonical_object_metrics,
    calculate_object_metrics,
    calculate_semantics_v2_object_metrics,
)
from .quality import calculate_quality_metrics
from .graph_algorithms import strong_components as _strong_components
from .projections import MetricsGraphProjection, iter_legacy_calls


def _calls_in(items: Iterable[Any]) -> int:
    return sum(1 for _ in iter_legacy_calls(items))


def _weak_components(
    nodes: set[str], edges: set[tuple[str, str]]
) -> list[set[str]]:
    neighbors = {node: set() for node in nodes}
    for source, target in edges:
        neighbors[source].add(target)
        neighbors[target].add(source)
    components: list[set[str]] = []
    unseen = set(nodes)
    while unseen:
        pending = [unseen.pop()]
        component: set[str] = set()
        while pending:
            node = pending.pop()
            component.add(node)
            discovered = neighbors[node] & unseen
            unseen -= discovered
            pending.extend(discovered)
        components.append(component)
    return components


def _degree_peak(degrees: Mapping[str, int]) -> dict[str, Any]:
    maximum = max(degrees.values(), default=0)
    return {
        "degree": maximum,
        "files": sorted(node for node, degree in degrees.items() if degree == maximum),
    }


def _directory_count(files: list[dict[str, Any]]) -> int:
    directories: set[tuple[str, ...]] = set()
    for file in files:
        parts = file.get("path_parts")
        if not isinstance(parts, (list, tuple)):
            parts = str(file.get("path") or "").split(".")
        clean = tuple(str(part) for part in parts if part)
        directories.update(clean[:index] for index in range(1, len(clean) + 1))
    return len(directories)


def _canonical_size(projection: MetricsGraphProjection) -> dict[str, int]:
    nodes = projection.nodes_by_id
    by_kind = projection.node_ids_by_kind
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
        "methods": sum(
            nodes[item].get("synthetic") is not True
            for item in by_kind.get("method", frozenset())
        ),
        "fields": len(by_kind.get("field", frozenset())),
        "constants": len(by_kind.get("constant", frozenset())),
    }


def calculate_graph_metrics(
    graph: Mapping[str, Any], *, canonical_mode: bool = False,
    legacy_resolution: bool | None = None, canonical_objects: bool = False,
    canonical_calls: bool = False,
) -> dict[str, Any]:
    """Return deterministic size, coupling, density and connectivity metrics."""
    projection = MetricsGraphProjection.from_graph(graph)
    semantics_v5_plus = projection.parser_semantics_version in {5, 6, 7}
    bodyless_semantics = projection.parser_semantics_version in {6, 7}
    files = [file.data for file in projection.legacy_files]
    file_graph = projection.directed_file_import_graph
    nodes = set(file_graph.nodes)
    edges = set(file_graph.edges)

    classes = [item for file in files for item in file.get("classes", [])]
    functions = [item for file in files for item in file.get("functions", [])]
    methods = [
        method
        for class_info in classes
        if isinstance(class_info, Mapping)
        for method in class_info.get("methods", [])
    ]
    fields = [
        field
        for class_info in classes
        if isinstance(class_info, Mapping)
        for field in class_info.get("fields", [])
    ]
    constants = [item for file in files for item in file.get("constants", [])]

    module_call_count = sum(_calls_in(file.get("calls", [])) for file in files)
    callable_call_count = sum(
        _calls_in(item.get("calls", []))
        for item in [*functions, *methods]
        if isinstance(item, Mapping)
    )
    call_count = module_call_count + callable_call_count
    local_imports = sum(
        1
        for file in files
        for item in file.get("imports", [])
        if isinstance(item, Mapping) and item.get("from_lib") is False
    )
    external_imports = sum(
        1
        for file in files
        for item in file.get("imports", [])
        if isinstance(item, Mapping) and item.get("from_lib") is True
    )
    if bodyless_semantics:
        facts = projection.owner_structural_facts_by_id
        roots = (projection.node_ids_by_kind.get("file", frozenset())
                 | projection.node_ids_by_kind.get("module", frozenset()))
        callable_ids = (
            projection.node_ids_by_kind.get("function", frozenset())
            | {identifier for identifier in projection.node_ids_by_kind.get("method", frozenset())
               if projection.nodes_by_id[identifier].get("synthetic") is not True}
        )
        module_call_count = sum(int(facts[item]["call_occurrences"]) for item in roots)
        callable_call_count = sum(int(facts[item]["call_occurrences"]) for item in callable_ids)
        call_count = module_call_count + callable_call_count
        local_imports = sum(int(facts[item]["direct_import_occurrences"]["project_local"]) for item in roots)
        external_imports = sum(int(facts[item]["direct_import_occurrences"]["non_project"]) for item in roots)

    fan_in = {node: 0 for node in nodes}
    fan_out = {node: 0 for node in nodes}
    for source, target in edges:
        fan_out[source] += 1
        fan_in[target] += 1

    weak_components = _weak_components(nodes, edges)
    cyclic_components = sorted([
        sorted(component)
        for component in _strong_components(nodes, edges)
        if len(component) > 1
    ])
    node_count = len(nodes)
    callable_count = len(callable_ids) if bodyless_semantics else len(functions) + len(methods)
    call_owner_count = (callable_count + sum(facts[item]["call_occurrences"] > 0 for item in roots)
                        if bodyless_semantics else callable_count + sum(bool(file.get("calls")) for file in files))
    method_count = (sum(projection.nodes_by_id[item].get("synthetic") is not True
                        for item in projection.node_ids_by_kind.get("method", frozenset()))
                    if bodyless_semantics else len(methods))
    class_count = (len(projection.node_ids_by_kind.get("class", frozenset()))
                   if bodyless_semantics else len(classes))
    if canonical_objects or semantics_v5_plus:
        object_metrics = (
            calculate_semantics_v2_object_metrics(graph, projection=projection)
            if projection.parser_semantics_version == 2
            else _calculate_canonical_object_metrics(projection)
        )
    else:
        object_metrics = calculate_object_metrics(
            graph, cyclic_dit_is_none=canonical_mode, projection=projection,
        )
    density_denominator = node_count * (node_count - 1)

    return {
        "size": _canonical_size(projection) if semantics_v5_plus else {
            "directories": _directory_count(files),
            "files": len(files),
            "classes": len(classes),
            "abstract_classes": sum(
                isinstance(item, Mapping) and item.get("type") == "abstract"
                for item in classes
            ),
            "dataclasses": sum(
                isinstance(item, Mapping) and item.get("type") == "dataclass"
                for item in classes
            ),
            "functions": len(functions),
            "methods": len(methods),
            "fields": len(fields),
            "constants": len(constants),
        },
        "activity": {
            "calls": call_count,
            "local_imports": local_imports,
            "external_imports": external_imports,
            "average_calls_per_callable": round(callable_call_count / callable_count, 4)
            if callable_count
            else 0.0,
            "average_calls_per_call_owner": round(call_count / call_owner_count, 4)
            if call_owner_count
            else 0.0,
            "average_methods_per_class": round(method_count / class_count, 4)
            if class_count
            else 0.0,
        },
        "dependency_graph": {
            "nodes": node_count,
            "edges": len(edges),
            "density": round(len(edges) / density_denominator, 4)
            if density_denominator
            else 0.0,
            "average_fan_in": round(len(edges) / node_count, 4)
            if node_count
            else 0.0,
            "average_fan_out": round(len(edges) / node_count, 4)
            if node_count
            else 0.0,
            "weakly_connected_components": len(weak_components),
            "isolated_files": sorted(
                node for node in nodes if fan_in[node] == fan_out[node] == 0
            ),
            "cyclic_components": cyclic_components,
            "highest_fan_in": _degree_peak(fan_in),
            "highest_fan_out": _degree_peak(fan_out),
        },
        "architecture": calculate_architecture_metrics(projection),
        "code_quality": calculate_quality_metrics(graph, projection=projection),
        "object_oriented": object_metrics,
        "call_graph": calculate_call_graph_metrics(
            graph, legacy_resolution=legacy_resolution,
            canonical=canonical_calls or semantics_v5_plus,
            projection=projection,
        ),
    }


def format_graph_metrics(metrics: Mapping[str, Any]) -> str:
    """Format metrics for readable terminal output."""
    return json.dumps(metrics, ensure_ascii=False, indent=2)
