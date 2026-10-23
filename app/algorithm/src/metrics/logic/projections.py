"""Immutable canonical topology views used by metric consumers."""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any


def _immutable_snapshot(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _immutable_snapshot(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_immutable_snapshot(item) for item in value)
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


def _package(path: Any) -> str:
    normalized = str(path or "")
    return normalized.split("/", 1)[0] if "/" in normalized else "<root>"


@dataclass(frozen=True, slots=True)
class MetricsGraphProjection:
    parser_semantics_version: int
    package_by_file_id: Mapping[str, str]
    nodes_by_id: Mapping[str, Mapping[str, Any]]
    node_ids_by_kind: Mapping[str, frozenset[str]]
    callsites: tuple[Mapping[str, Any], ...]
    import_references: tuple[Mapping[str, Any], ...]
    owner_structural_facts_by_id: Mapping[str, Mapping[str, Any]]
    directed_file_import_graph: DirectedGraphProjection
    directed_package_import_graph: DirectedGraphProjection
    undirected_file_import_graph: UndirectedGraphProjection
    directed_canonical_call_graph: WeightedDirectedGraphProjection
    directed_canonical_inheritance_graph: DirectedGraphProjection
    directed_canonical_field_type_graph: DirectedGraphProjection
    directed_canonical_field_access_graph: DirectedGraphProjection

    @classmethod
    def from_graph(cls, graph: Mapping[str, Any]) -> "MetricsGraphProjection":
        raw_nodes = {str(node["id"]): _immutable_snapshot(node) for node in graph["nodes"]}
        kinds: dict[str, set[str]] = {}
        for identifier, node in raw_nodes.items():
            kinds.setdefault(str(node.get("kind")), set()).add(identifier)
        roots = frozenset(kinds.get("file", set()) | kinds.get("module", set()))
        package_of = {identifier: _package(raw_nodes[identifier].get("path")) for identifier in roots}
        file_edges: set[tuple[str, str]] = set()
        weights: Counter[tuple[str, str]] = Counter()
        relations = {"inherits": set(), "field_type": set(), "accesses_field": set()}
        relation_kinds = {"inherits": ("class", "class"), "field_type": ("field", "class"), "accesses_field": ("method", "field")}
        for edge in graph["edges"]:
            kind = edge.get("kind"); source = str(edge.get("source_id")); target = str(edge.get("target_id"))
            if kind == "imports" and source in roots and target in roots and source != target:
                file_edges.add((source, target))
            if kind in {"calls", "awaits"} and source in raw_nodes and target in raw_nodes:
                weights[(source, target)] += int(edge.get("weight", 1))
            if kind in relation_kinds and source in raw_nodes and target in raw_nodes:
                source_kind, target_kind = relation_kinds[kind]
                if raw_nodes[source].get("kind") == source_kind and raw_nodes[target].get("kind") == target_kind:
                    relations[kind].add((source, target))
        packages = frozenset(package_of.values())
        package_edges = frozenset((package_of[s], package_of[t]) for s, t in file_edges if package_of[s] != package_of[t])
        owner_facts = {str(fact["owner_id"]): _immutable_snapshot(fact) for fact in graph["owner_structural_facts"]}
        return cls(
            int(graph["parser_semantics_version"]), MappingProxyType(package_of), MappingProxyType(raw_nodes),
            MappingProxyType({kind: frozenset(ids) for kind, ids in kinds.items()}),
            tuple(_immutable_snapshot(item) for item in graph["callsites"]),
            tuple(_immutable_snapshot(item) for item in graph["import_references"]),
            MappingProxyType(owner_facts), DirectedGraphProjection(roots, frozenset(file_edges)),
            DirectedGraphProjection(packages, package_edges),
            UndirectedGraphProjection(roots, frozenset(tuple(sorted(edge)) for edge in file_edges)),
            WeightedDirectedGraphProjection(frozenset(raw_nodes), MappingProxyType(dict(weights))),
            DirectedGraphProjection(frozenset(kinds.get("class", ())), frozenset(relations["inherits"])),
            DirectedGraphProjection(frozenset((*kinds.get("field", ()), *kinds.get("class", ()))), frozenset(relations["field_type"])),
            DirectedGraphProjection(frozenset((*kinds.get("method", ()), *kinds.get("field", ()))), frozenset(relations["accesses_field"])),
        )
