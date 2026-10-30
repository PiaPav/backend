"""Graph-native compact ``aggregate.overview/1`` projection."""
from __future__ import annotations

from collections import Counter
from typing import Any, Mapping

from graph_dto import validate_graph_v1
from ..aggregate_overview_contract import aggregate_overview_package_id
from ..registry import summary_profile_metadata
from ..summary_contract import graph_summary_fingerprint, validate_graph_summary_v1


def _package(path: str) -> str:
    return path.split("/", 1)[0] if "/" in path else "<root>"


def _scc(vertices: set[str], edges: set[tuple[str, str]]) -> int:
    adjacency = {v: [] for v in vertices}
    reverse = {v: [] for v in vertices}
    for source, target in edges:
        adjacency[source].append(target)
        reverse[target].append(source)

    ordered_adjacency = {vertex: sorted(targets) for vertex, targets in adjacency.items()}
    ordered_reverse = {vertex: sorted(sources) for vertex, sources in reverse.items()}
    visited = set()
    finished = []
    for vertex in sorted(vertices):
        if vertex in visited:
            continue
        visited.add(vertex)
        stack = [(vertex, 0)]
        while stack:
            current, next_index = stack[-1]
            targets = ordered_adjacency[current]
            if next_index < len(targets):
                target = targets[next_index]
                stack[-1] = (current, next_index + 1)
                if target not in visited:
                    visited.add(target)
                    stack.append((target, 0))
            else:
                finished.append(current)
                stack.pop()

    visited.clear()
    count = 0
    for vertex in reversed(finished):
        if vertex in visited:
            continue
        size = 0
        visited.add(vertex)
        stack = [vertex]
        while stack:
            current = stack.pop()
            size += 1
            for source in reversed(ordered_reverse[current]):
                if source not in visited:
                    visited.add(source)
                    stack.append(source)
        count += size > 1
    return count


def project_aggregate_overview_v1(source_graph: Mapping[str, Any]) -> dict[str, Any]:
    validate_graph_v1(source_graph)
    return _project_aggregate_overview_v1(source_graph)


def _project_aggregate_overview_v1(graph: Mapping[str, Any]) -> dict[str, Any]:
    if graph["schema_version"] != 1 or graph["parser_semantics_version"] != 7:
        raise ValueError("aggregate.overview v1 requires Graph DTO schema 1 / parser semantics 7")
    nodes = graph["nodes"]
    roots = {n["id"]: n for n in nodes if n["parent_id"] is None}
    labels = {identifier: _package(node["path"]) for identifier, node in roots.items()}
    edges = {(r["importer_id"], r["target_id"]) for r in graph["import_references"]
             if r["resolution"] == "exact" and r["importer_id"] != r["target_id"]}
    package_edges = {(labels[s], labels[t]) for s, t in edges if labels[s] != labels[t]}
    prefixes = {"/".join(n["path"].split("/")[:i]) for n in roots.values()
                for i in range(1, len(n["path"].split("/")))}
    facts = {f["owner_id"]: f for f in graph["owner_structural_facts"]}
    owners = [n for n in nodes if n["parent_id"] is None or n["kind"] == "function"
              or (n["kind"] == "method" and n.get("synthetic") is not True)]
    root_facts = [facts[identifier] for identifier in roots]
    totals = [len(prefixes), len(roots), sum(n["kind"] == "class" for n in nodes),
              sum(n["kind"] == "class" and n.get("class_kind") == "abstract" for n in nodes),
              sum(n["kind"] == "class" and n.get("class_kind") == "dataclass" for n in nodes),
              sum(n["kind"] == "function" for n in nodes),
              sum(n["kind"] == "method" and n.get("synthetic") is not True for n in nodes),
              sum(n["kind"] == "method" and n.get("synthetic") is True for n in nodes),
              sum(n["kind"] == "field" for n in nodes), sum(n["kind"] == "constant" for n in nodes),
              sum(facts[n["id"]]["call_occurrences"] for n in owners),
              sum(f["direct_import_occurrences"]["project_local"] for f in root_facts),
              sum(f["direct_import_occurrences"]["non_project"] for f in root_facts),
              len(roots), len(edges), _scc(set(roots), edges), len(set(labels.values())),
              len(package_edges), _scc(set(labels.values()), package_edges)]
    counters = [Counter(r["resolution"] for r in graph[key]) for key in
                ("import_references", "type_references", "callsites")]
    statuses = ([counters[0][s] for s in ("exact", "external", "unresolved")] +
                [counters[1][s] for s in ("exact", "ambiguous", "external", "unresolved")] +
                [counters[2][s] for s in ("exact", "ambiguous", "external", "dynamic", "unresolved")])
    ranked = []
    for counter, transform in ((Counter(t for _, t in edges), lambda x: x),
                               (Counter(s for s, _ in edges), lambda x: x),
                               (Counter(s for s, _ in package_edges), aggregate_overview_package_id)):
        ranked.append(sorted(((transform(key), score) for key, score in counter.items() if score > 0),
                             key=lambda row: (-row[1], row[0])))
    file_selected = sorted({identifier for ranking in ranked[:2] for identifier, _ in ranking[:10]})
    package_selected = sorted({identifier for identifier, _ in ranked[2][:10]})
    file_rows = [[identifier, roots[identifier]["path"]] for identifier in file_selected]
    package_labels = {aggregate_overview_package_id(label): label for label in set(labels.values())}
    package_rows = [[identifier, package_labels[identifier]] for identifier in package_selected]
    indexes = [{row[0]: i for i, row in enumerate(file_rows)},
               {row[0]: i for i, row in enumerate(package_rows)}]
    ranking_rows = []
    for ordinal, ranking in enumerate(ranked):
        returned = ranking[:10]
        ranking_rows.append([len(ranking), len(returned), len(returned) < len(ranking),
                             [[indexes[ordinal == 2][identifier], score] for identifier, score in returned]])
    summary = {"artifact_kind": "graph_summary", "summary_schema_version": 1,
               "profile": {"id": "aggregate.overview", "version": 1},
               "source": {"graph_schema_version": 1, "parser_semantics_version": 7,
                          "graph_fingerprint": graph["project"]["fingerprint"]},
               "completeness": summary_profile_metadata("aggregate.overview", 1),
               "payload": {"graph_kind": "overview", "wire_format": 1, "policy_version": 1,
                           "totals": totals, "statuses": statuses, "file_identities": file_rows,
                           "package_identities": package_rows, "rankings": ranking_rows},
               "summary_fingerprint": "0" * 64}
    summary["summary_fingerprint"] = graph_summary_fingerprint(summary)
    validate_graph_summary_v1(summary)
    return summary


__all__ = ["project_aggregate_overview_v1"]
