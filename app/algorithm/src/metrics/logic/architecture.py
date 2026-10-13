"""Package balance and critical topology metrics for file dependency graphs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def _package(file: Mapping[str, Any]) -> str:
    parts = file.get("path_parts")
    if isinstance(parts, list) and parts:
        return str(parts[0])
    path = str(file.get("path") or "")
    return path.split(".", 1)[0] if path else "<root>"


def _critical_topology(
    nodes: set[str], edges: set[tuple[str, str]]
) -> tuple[list[str], list[list[str]]]:
    adjacency = {node: set() for node in nodes}
    for source, target in edges:
        adjacency[source].add(target)
        adjacency[target].add(source)
    time = 0
    discovered: dict[str, int] = {}
    low: dict[str, int] = {}
    parent: dict[str, str | None] = {}
    articulation: set[str] = set()
    bridges: set[tuple[str, str]] = set()

    def visit(node: str) -> None:
        nonlocal time
        discovered[node] = low[node] = time
        time += 1
        children = 0
        for target in adjacency[node]:
            if target not in discovered:
                parent[target] = node
                children += 1
                visit(target)
                low[node] = min(low[node], low[target])
                if parent[node] is None and children > 1:
                    articulation.add(node)
                if parent[node] is not None and low[target] >= discovered[node]:
                    articulation.add(node)
                if low[target] > discovered[node]:
                    bridges.add(tuple(sorted((node, target))))
            elif target != parent[node]:
                low[node] = min(low[node], discovered[target])

    for node in sorted(nodes):
        if node not in discovered:
            parent[node] = None
            visit(node)
    return sorted(articulation), [list(edge) for edge in sorted(bridges)]


def _cyclic_components(
    nodes: set[str], edges: set[tuple[str, str]]
) -> list[list[str]]:
    adjacency = {node: set() for node in nodes}
    for source, target in edges:
        adjacency[source].add(target)
    index = 0
    indices: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    cycles: list[list[str]] = []

    def visit(node: str) -> None:
        nonlocal index
        indices[node] = low[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for target in adjacency[node]:
            if target not in indices:
                visit(target)
                low[node] = min(low[node], low[target])
            elif target in on_stack:
                low[node] = min(low[node], indices[target])
        if low[node] != indices[node]:
            return
        component: list[str] = []
        while True:
            target = stack.pop()
            on_stack.remove(target)
            component.append(target)
            if target == node:
                break
        if len(component) > 1:
            cycles.append(sorted(component))

    for node in sorted(nodes):
        if node not in indices:
            visit(node)
    return sorted(cycles)


def calculate_architecture_metrics(
    files: list[dict[str, Any]],
    nodes: set[str],
    edges: set[tuple[str, str]],
    file_id,
) -> dict[str, Any]:
    package_of = {_file_id: _package(file) for file in files if (_file_id := file_id(file))}
    packages = set(package_of.values())
    package_edges = {
        (package_of[source], package_of[target])
        for source, target in edges
        if package_of[source] != package_of[target]
    }
    incoming = {package: set() for package in packages}
    outgoing = {package: set() for package in packages}
    for source, target in package_edges:
        outgoing[source].add(target)
        incoming[target].add(source)

    class_counts = {package: 0 for package in packages}
    abstract_counts = {package: 0 for package in packages}
    for file in files:
        package = package_of[file_id(file)]
        for class_info in file.get("classes", []):
            if not isinstance(class_info, Mapping):
                continue
            class_counts[package] += 1
            abstract_counts[package] += class_info.get("type") == "abstract"

    package_metrics = []
    for package in sorted(packages):
        afferent = len(incoming[package])
        efferent = len(outgoing[package])
        total_coupling = afferent + efferent
        instability = efferent / total_coupling if total_coupling else 0.0
        abstractness = (
            abstract_counts[package] / class_counts[package]
            if class_counts[package]
            else 0.0
        )
        package_metrics.append(
            {
                "package": package,
                "files": sum(value == package for value in package_of.values()),
                "classes": class_counts[package],
                "abstract_classes": abstract_counts[package],
                "afferent_coupling": afferent,
                "efferent_coupling": efferent,
                "instability": round(instability, 4),
                "abstractness": round(abstractness, 4),
                "distance_from_main_sequence": round(
                    abs(abstractness + instability - 1), 4
                ),
            }
        )

    articulation, bridges = _critical_topology(nodes, edges)
    return {
        "packages": package_metrics,
        "package_edges": len(package_edges),
        "cyclic_package_components": _cyclic_components(packages, package_edges),
        "articulation_files": articulation,
        "bridge_dependencies": bridges,
    }
