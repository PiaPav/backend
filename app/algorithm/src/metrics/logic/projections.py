"""Immutable topology and compatibility views used by metric consumers."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from .identity import (
    effective_module_ids,
    graph_files,
    legacy_file_id,
    semantic_module_name,
)


def _immutable_snapshot(value: Any) -> Any:
    """Recursively detach JSON-like data and make every container immutable."""
    if isinstance(value, Mapping):
        return MappingProxyType({
            key: _immutable_snapshot(item) for key, item in value.items()
        })
    if isinstance(value, (list, tuple)):
        return tuple(_immutable_snapshot(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_immutable_snapshot(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class DirectedGraphProjection:
    nodes: frozenset[str]
    edges: frozenset[tuple[str, str]]


@dataclass(frozen=True, slots=True)
class UndirectedGraphProjection:
    nodes: frozenset[str]
    edges: frozenset[tuple[str, str]]


@dataclass(frozen=True, slots=True)
class WeightedDirectedGraphProjection:
    nodes: frozenset[str]
    edge_weights: Mapping[tuple[str, str], int]

    @property
    def edges(self) -> frozenset[tuple[str, str]]:
        return frozenset(self.edge_weights)


@dataclass(frozen=True, slots=True)
class LegacyFileProjection:
    data: Mapping[str, Any]
    file_id: str
    semantic_module: str
    package: str


@dataclass(frozen=True, slots=True)
class LegacyCallProjection:
    call: Mapping[str, Any]
    depth: int


def iter_legacy_calls(
    calls: Iterable[Any], initial_depth: int = 1
) -> Iterator[LegacyCallProjection]:
    """Yield mapping call records and nested argument calls in historical order."""
    for raw_call in calls:
        if not isinstance(raw_call, Mapping):
            continue
        yield LegacyCallProjection(_immutable_snapshot(raw_call), initial_depth)
        for argument in raw_call.get("args", []):
            if not isinstance(argument, Mapping):
                continue
            value = argument.get("value")
            if isinstance(value, Mapping) and value.get("type") == "call":
                yield from iter_legacy_calls((value,), initial_depth + 1)


def _package(file: Mapping[str, Any]) -> str:
    parts = file.get("path_parts")
    if isinstance(parts, list) and parts:
        return str(parts[0])
    path = str(file.get("path") or "")
    return path.split(".", 1)[0] if path else "<root>"


def _canonical_package(path: Any) -> str:
    """Return package identity for a canonical relative file path."""
    normalized = str(path or "")
    return normalized.split("/", 1)[0] if "/" in normalized else "<root>"


@dataclass(frozen=True, slots=True)
class MetricsGraphProjection:
    parser_semantics_version: int | None
    legacy_files: tuple[LegacyFileProjection, ...]
    effective_module_ids: Mapping[str, str]
    nodes_by_id: Mapping[str, Mapping[str, Any]]
    node_ids_by_kind: Mapping[str, frozenset[str]]
    callsites: tuple[Mapping[str, Any], ...]
    import_references: tuple[Mapping[str, Any], ...]
    directed_file_import_graph: DirectedGraphProjection
    directed_package_import_graph: DirectedGraphProjection
    undirected_file_import_graph: UndirectedGraphProjection
    directed_canonical_call_graph: WeightedDirectedGraphProjection

    @classmethod
    def from_graph(cls, graph: Mapping[str, Any]) -> "MetricsGraphProjection":
        raw_files = graph_files(graph)
        files = tuple(
            LegacyFileProjection(
                _immutable_snapshot(file), legacy_file_id(file),
                semantic_module_name(file), _package(file),
            )
            for file in raw_files
        )
        module_ids = effective_module_ids(raw_files)
        raw_nodes = {
            str(node["id"]): _immutable_snapshot(node)
            for node in graph.get("nodes", [])
            if isinstance(node, Mapping) and "id" in node
        }
        canonical_imports = int(graph.get("parser_semantics_version") or 0) >= 4
        file_nodes = (
            frozenset(identifier for identifier, node in raw_nodes.items() if node.get("kind") in {"file", "module"})
            if canonical_imports else frozenset(file.file_id for file in files)
        )
        file_edges: set[tuple[str, str]] = set()
        if canonical_imports:
            for edge in graph.get("edges", []):
                if not isinstance(edge, Mapping) or edge.get("kind") != "imports":
                    continue
                source, target = str(edge.get("source_id")), str(edge.get("target_id"))
                if source in file_nodes and target in file_nodes and source != target:
                    file_edges.add((source, target))
        else:
            for file in files:
                for imported in file.data.get("imports", []):
                    if not isinstance(imported, Mapping) or imported.get("from_lib") is not False:
                        continue
                    path = str(imported.get("path") or "")
                    target = module_ids.get(path, path)
                    if target in file_nodes and target != file.file_id:
                        file_edges.add((file.file_id, target))

        package_of = {file.file_id: file.package for file in files}
        if canonical_imports:
            package_of = {
                identifier: _canonical_package(node.get("path"))
                for identifier, node in raw_nodes.items() if identifier in file_nodes
            }
        packages = frozenset(package_of.values())
        package_edges = frozenset(
            (package_of[source], package_of[target])
            for source, target in file_edges
            if package_of[source] != package_of[target]
        )
        undirected_edges = frozenset(tuple(sorted(edge)) for edge in file_edges)

        kinds: dict[str, set[str]] = {}
        for identifier, node in raw_nodes.items():
            kinds.setdefault(str(node.get("kind")), set()).add(identifier)
        callsites = tuple(
            _immutable_snapshot(callsite)
            for callsite in graph.get("callsites", [])
            if isinstance(callsite, Mapping)
        )
        import_references = tuple(
            _immutable_snapshot(reference)
            for reference in graph.get("import_references", [])
            if isinstance(reference, Mapping)
        )
        weights: Counter[tuple[str, str]] = Counter()
        for edge in graph.get("edges", []):
            if not isinstance(edge, Mapping) or edge.get("kind") not in {"calls", "awaits"}:
                continue
            source, target = edge.get("source_id"), edge.get("target_id")
            if source in raw_nodes and target in raw_nodes:
                weights[(str(source), str(target))] += int(edge.get("weight", 1))

        return cls(
            parser_semantics_version=graph.get("parser_semantics_version"),
            legacy_files=files,
            effective_module_ids=MappingProxyType(dict(module_ids)),
            nodes_by_id=MappingProxyType(raw_nodes),
            node_ids_by_kind=MappingProxyType({
                kind: frozenset(identifiers) for kind, identifiers in kinds.items()
            }),
            callsites=callsites,
            import_references=import_references,
            directed_file_import_graph=DirectedGraphProjection(file_nodes, frozenset(file_edges)),
            directed_package_import_graph=DirectedGraphProjection(packages, package_edges),
            undirected_file_import_graph=UndirectedGraphProjection(file_nodes, undirected_edges),
            directed_canonical_call_graph=WeightedDirectedGraphProjection(
                frozenset(raw_nodes), MappingProxyType(dict(weights))
            ),
        )
