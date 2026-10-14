"""Package balance and critical topology metrics for file dependency graphs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .graph_algorithms import strong_components


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

    for root in sorted(nodes):
        if root in discovered:
            continue
        parent[root] = None
        discovered[root] = low[root] = time
        time += 1
        child_counts = {root: 0}
        stack = [(root, iter(sorted(adjacency[root])))]
        while stack:
            node, targets = stack[-1]
            try:
                target = next(targets)
            except StopIteration:
                stack.pop()
                ancestor = parent[node]
                if ancestor is None:
                    if child_counts[node] > 1:
                        articulation.add(node)
                    continue
                low[ancestor] = min(low[ancestor], low[node])
                if parent[ancestor] is not None and low[node] >= discovered[ancestor]:
                    articulation.add(ancestor)
                if low[node] > discovered[ancestor]:
                    bridges.add(tuple(sorted((ancestor, node))))
                continue
            if target not in discovered:
                parent[target] = node
                child_counts[node] += 1
                child_counts[target] = 0
                discovered[target] = low[target] = time
                time += 1
                stack.append((target, iter(sorted(adjacency[target]))))
            elif target != parent[node]:
                low[node] = min(low[node], discovered[target])
    return sorted(articulation), [list(edge) for edge in sorted(bridges)]


def _cyclic_components(
    nodes: set[str], edges: set[tuple[str, str]]
) -> list[list[str]]:
    return sorted(
        sorted(component)
        for component in strong_components(nodes, edges)
        if len(component) > 1
    )


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
