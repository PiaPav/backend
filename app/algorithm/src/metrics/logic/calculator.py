"""Calculate project-size and file-dependency metrics from a parser graph."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

from .architecture import calculate_architecture_metrics
from .call_graph import calculate_call_graph_metrics
from .object_metrics import calculate_object_metrics
from .quality import calculate_quality_metrics
from .identity import effective_module_ids, graph_files, legacy_file_id
from .graph_algorithms import strong_components as _strong_components


def _file_id(file: Mapping[str, Any]) -> str:
    return legacy_file_id(file)


def _files(graph: Mapping[str, Any]) -> list[dict[str, Any]]:
    return graph_files(graph)


def _count_call(call: Mapping[str, Any]) -> int:
    count = 1
    for argument in call.get("args", []):
        if not isinstance(argument, Mapping):
            continue
        value = argument.get("value")
        if isinstance(value, Mapping) and value.get("type") == "call":
            count += _count_call(value)
    return count


def _calls_in(items: Iterable[Any]) -> int:
    return sum(
        _count_call(item) for item in items if isinstance(item, Mapping)
    )


def _dependency_edges(
    files: list[dict[str, Any]], nodes: set[str]
) -> set[tuple[str, str]]:
    edges: set[tuple[str, str]] = set()
    modules = effective_module_ids(files)
    for file in files:
        source = _file_id(file)
        for imported in file.get("imports", []):
            if not isinstance(imported, Mapping) or imported.get("from_lib") is not False:
                continue
            target = modules.get(str(imported.get("path") or ""), str(imported.get("path") or ""))
            if target in nodes and target != source:
                edges.add((source, target))
    return edges


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
        if not isinstance(parts, list):
            parts = str(file.get("path") or "").split(".")
        clean = tuple(str(part) for part in parts if part)
        directories.update(clean[:index] for index in range(1, len(clean) + 1))
    return len(directories)


def calculate_graph_metrics(
    graph: Mapping[str, Any], *, canonical_mode: bool = False,
    legacy_resolution: bool | None = None,
) -> dict[str, Any]:
    """Return deterministic size, coupling, density and connectivity metrics."""
    files = _files(graph)
    nodes = {_file_id(file) for file in files}
    edges = _dependency_edges(files, nodes)

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
    callable_count = len(functions) + len(methods)
    call_owner_count = callable_count + sum(bool(file.get("calls")) for file in files)
    density_denominator = node_count * (node_count - 1)

    return {
        "size": {
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
            "average_methods_per_class": round(len(methods) / len(classes), 4)
            if classes
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
        "architecture": calculate_architecture_metrics(files, nodes, edges, _file_id),
        "code_quality": calculate_quality_metrics(graph),
        "object_oriented": calculate_object_metrics(graph, cyclic_dit_is_none=canonical_mode),
        "call_graph": calculate_call_graph_metrics(
            graph, legacy_resolution=legacy_resolution
        ),
    }


def format_graph_metrics(metrics: Mapping[str, Any]) -> str:
    """Format metrics for readable terminal output."""
    return json.dumps(metrics, ensure_ascii=False, indent=2)
