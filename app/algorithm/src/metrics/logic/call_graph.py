"""Function- and method-level call graph construction and metrics."""

from __future__ import annotations

from collections import Counter, deque
from collections.abc import Mapping
from typing import Any

from .complexity import canonical_callable_metrics
from .graph_algorithms import strong_components as _strong_components
from .projections import MetricsGraphProjection


def _longest_component_indices(
    components: list[set[str]],
    edges: set[tuple[str, str]],
    display_key: Mapping[str, str] | None = None,
) -> list[int]:
    if not components:
        return []
    component_of = {
        node: index for index, component in enumerate(components) for node in component
    }
    adjacency = {index: set() for index in range(len(components))}
    for source, target in edges:
        left, right = component_of[source], component_of[target]
        if left != right:
            adjacency[left].add(right)
    cache: dict[int, list[int]] = {}

    def component_label(index: int) -> str:
        component = components[index]
        if len(component) == 1:
            return next(iter(component))
        return "{" + " ↔ ".join(sorted(component)) + "}"

    def component_key(index: int) -> str | tuple[str, ...]:
        if display_key is None:
            return component_label(index)
        return tuple(sorted(display_key[node] for node in components[index]))

    def path_key(path: list[int]) -> tuple[str | tuple[str, ...], ...]:
        return tuple(component_key(index) for index in path)

    remaining = set(adjacency)
    while remaining:
        ready = sorted(index for index in remaining if adjacency[index] <= cache.keys())
        if not ready: raise ValueError("component graph must be acyclic")
        for start in ready:
            tails = [cache[target] for target in adjacency[start]]
            best_tail = min(tails, key=lambda tail: (-len(tail), path_key(tail))) if tails else []
            cache[start] = [start, *best_tail]
            remaining.remove(start)

    return min(
        cache.values(),
        key=lambda candidate: (-len(candidate), path_key(candidate)),
    )


def _pagerank(nodes: set[str], edges: set[tuple[str, str]]) -> dict[str, float]:
    if not nodes:
        return {}
    adjacency = {node: set() for node in nodes}
    for source, target in edges:
        adjacency[source].add(target)
    count = len(nodes)
    rank = {node: 1 / count for node in nodes}
    damping = 0.85
    for _ in range(100):
        dangling = sum(rank[node] for node in nodes if not adjacency[node]) / count
        updated = {node: (1 - damping) / count + damping * dangling for node in nodes}
        for source, targets in adjacency.items():
            if targets:
                share = damping * rank[source] / len(targets)
                for target in targets:
                    updated[target] += share
        if max(abs(updated[node] - rank[node]) for node in nodes) < 1e-10:
            rank = updated
            break
        rank = updated
    return rank


def _betweenness(nodes: set[str], edges: set[tuple[str, str]]) -> dict[str, float]:
    adjacency = {node: set() for node in nodes}
    for source, target in edges:
        adjacency[source].add(target)
    centrality = {node: 0.0 for node in nodes}
    for source in nodes:
        stack: list[str] = []
        predecessors = {node: [] for node in nodes}
        paths = dict.fromkeys(nodes, 0.0)
        paths[source] = 1.0
        distance = dict.fromkeys(nodes, -1)
        distance[source] = 0
        queue = deque([source])
        while queue:
            node = queue.popleft()
            stack.append(node)
            for target in adjacency[node]:
                if distance[target] < 0:
                    queue.append(target)
                    distance[target] = distance[node] + 1
                if distance[target] == distance[node] + 1:
                    paths[target] += paths[node]
                    predecessors[target].append(node)
        dependency = dict.fromkeys(nodes, 0.0)
        while stack:
            target = stack.pop()
            for node in predecessors[target]:
                dependency[node] += (paths[node] / paths[target]) * (1 + dependency[target])
            if target != source:
                centrality[target] += dependency[target]
    normalizer = (len(nodes) - 1) * (len(nodes) - 2)
    if normalizer > 0:
        centrality = {node: value / normalizer for node, value in centrality.items()}
    return centrality


def _top(values: Mapping[str, float], limit: int = 5) -> list[dict[str, Any]]:
    return [
        {"node": node, "score": round(score, 6)}
        for node, score in sorted(values.items(), key=lambda item: (-item[1], item[0]))[:limit]
    ]


def calculate_call_graph_metrics(
    graph: Mapping[str, Any], *, projection: MetricsGraphProjection | None = None,
) -> dict[str, Any]:
    """Canonical gateway for call-graph metrics."""
    if projection is None:
        from .calculator import validate_metrics_graph
        validate_metrics_graph(graph)
        projection = MetricsGraphProjection.from_graph(graph)
    return _calculate_call_graph_metrics(projection)


def _calculate_call_graph_metrics(
    projection: MetricsGraphProjection,
) -> dict[str, Any]:
    return _calculate_canonical_call_graph_metrics(projection)


def _calculate_canonical_call_graph_metrics(
    projection: MetricsGraphProjection,
) -> dict[str, Any]:
    """Build canonical topology from IDs and classify canonical callsites."""
    all_nodes = projection.nodes_by_id
    callable_ids = {identifier for identifier, item in all_nodes.items() if item.get("kind") in {"function", "method"}}
    file_nodes = {
        identifier: item for identifier, item in all_nodes.items()
        if item.get("kind") in {"file", "module"}
    }
    module_paths: dict[str, set[str]] = {}
    for item in file_nodes.values():
        module_paths.setdefault(str(item.get("qualified_name") or ""), set()).add(str(item.get("path") or ""))
    active_modules = {
        str(callsite.get("caller_id"))
        for callsite in projection.callsites
        if callsite.get("caller_id") in file_nodes
    }
    active_modules.update(
        source
        for source, _ in projection.directed_canonical_call_graph.edges
        if source in file_nodes
    )
    call_owner_ids = callable_ids | active_modules

    def ancestor_file(identifier: str) -> Mapping[str, Any] | None:
        current = all_nodes[identifier]
        seen: set[str] = set()
        while current.get("parent_id") in all_nodes:
            parent_id = str(current["parent_id"])
            if parent_id in seen:
                return None
            seen.add(parent_id); current = all_nodes[parent_id]
        return current if current.get("kind") in {"file", "module"} else None

    def label(identifier: str) -> str:
        item = all_nodes[identifier]; qualified = str(item.get("qualified_name") or identifier)
        file_node = ancestor_file(identifier)
        path = str((file_node or item).get("path") or "")
        module = str(file_node.get("qualified_name") or "") if file_node else qualified.rsplit(".", 1)[0]
        if identifier in file_nodes:
            return (
                f"file:{path}.__module__"
                if len(module_paths.get(qualified, ())) > 1
                else f"{qualified}.__module__"
            )
        # Preserve the established collision-safe file provenance spelling.
        if len(module_paths.get(module, ())) > 1:
            suffix = qualified[len(module):].lstrip(".")
            return f"file:{path}.{suffix}" if suffix else f"file:{path}"
        return qualified

    base_labels = {identifier: label(identifier) for identifier in call_owner_ids}
    label_counts = Counter(base_labels.values())
    labels = {
        identifier: (
            value if label_counts[value] == 1 else f"{value} [{identifier}]"
        )
        for identifier, value in base_labels.items()
    }
    edge_weights: Counter[tuple[str, str]] = Counter()
    for (source, target), weight in projection.directed_canonical_call_graph.edge_weights.items():
        if source in call_owner_ids and target in callable_ids:
            edge_weights[(source, target)] += weight
    edges = set(edge_weights)
    external = unresolved = 0; maximum_nesting = 0; deepest: set[str] = set()
    for callsite in projection.callsites:
        caller = callsite.get("caller_id"); status = callsite.get("resolution")
        if caller not in call_owner_ids:
            continue
        depth = int(callsite.get("syntactic_depth", 0)) + 1
        if depth > maximum_nesting: maximum_nesting = depth; deepest = {caller}
        elif depth == maximum_nesting: deepest.add(caller)
        if status == "external": external += 1
        elif status != "exact": unresolved += 1

    incoming = dict.fromkeys(call_owner_ids, 0); outgoing = dict.fromkeys(call_owner_ids, 0)
    adjacency = {node: set() for node in call_owner_ids}
    for source, target in edges:
        outgoing[source] += 1; incoming[target] += 1; adjacency[source].add(target)
    components = _strong_components(call_owner_ids, edges)
    recursive_ids = [sorted(component) for component in components if len(component) > 1 or any((node, node) in edges for node in component)]
    longest_component_indices = _longest_component_indices(
        components, edges, display_key=labels
    )
    longest = []
    for index in longest_component_indices:
        component_labels = sorted(labels[identifier] for identifier in components[index])
        longest.append(
            component_labels[0]
            if len(component_labels) == 1
            else "{" + " ↔ ".join(component_labels) + "}"
        )
    reach: dict[str, int] = {}
    for start in call_owner_ids:
        visited: set[str] = set(); pending = list(adjacency[start])
        while pending:
            node = pending.pop()
            if node in visited: continue
            visited.add(node); pending.extend(adjacency[node] - visited)
        visited.discard(start); reach[start] = len(visited)
    peak_in = max(incoming.values(), default=0); peak_out = max(outgoing.values(), default=0)
    peak_reach = max(reach.values(), default=0)
    pagerank = _pagerank(call_owner_ids, edges); betweenness = _betweenness(call_owner_ids, edges)
    complexity = canonical_callable_metrics(projection)
    risk_nodes = {
        node for node in call_owner_ids
        if all_nodes[node].get("synthetic") is not True
    }
    complexity_raw = {
        node: max(0, int(complexity.get(node, {}).get("cyclomatic_complexity", 1)) - 1)
        + int(complexity.get(node, {}).get("cognitive_complexity", 0))
        for node in risk_nodes
    }
    peak_complexity = max(complexity_raw.values(), default=0)
    risk_peak_in = max((incoming[node] for node in risk_nodes), default=0)
    peak_betweenness = max((betweenness[node] for node in risk_nodes), default=0.0)
    risk_peak_reach = max((reach[node] for node in risk_nodes), default=0)
    risks = []
    for node in risk_nodes:
        score = 100 * (
            0.35 * (complexity_raw[node] / peak_complexity if peak_complexity else 0.0)
            + 0.25 * (incoming[node] / risk_peak_in if risk_peak_in else 0.0)
            + 0.20 * (betweenness[node] / peak_betweenness if peak_betweenness else 0.0)
            + 0.20 * (reach[node] / risk_peak_reach if risk_peak_reach else 0.0)
        )
        if score:
            risks.append({
                "node": labels[node], "score": round(score, 2),
                "cyclomatic": int(complexity.get(node, {}).get("cyclomatic_complexity", 0)),
                "cognitive": int(complexity.get(node, {}).get("cognitive_complexity", 0)),
                "fan_in": incoming[node], "betweenness": round(betweenness[node], 6),
                "transitive_reach": reach[node],
            })
    risks.sort(key=lambda item: (-item["score"], item["node"]))
    local = sum(edge_weights.values()); total = local + external + unresolved
    return {
        "nodes": len(call_owner_ids), "edges": len(edges), "callsites_in_local_edges": local,
        "external_or_builtin_callsites": external, "unresolved_callsites": unresolved,
        "unresolved_or_external_callsites": external + unresolved,
        "local_resolution_rate": round(local / total, 4) if total else 0.0,
        "classified_callsite_rate": round((local + external) / total, 4) if total else 0.0,
        "heaviest_edges": [{"caller": labels[s], "target": labels[t], "callsites": weight} for (s, t), weight in sorted(edge_weights.items(), key=lambda item: (-item[1], labels[item[0][0]], labels[item[0][1]]))[:10]],
        "entrypoints": sorted(labels[node] for node in call_owner_ids if incoming[node] == 0 and outgoing[node] > 0),
        "leaf_callables": sorted(labels[node] for node in call_owner_ids if incoming[node] > 0 and outgoing[node] == 0),
        "isolated_callables": sorted(labels[node] for node in call_owner_ids if incoming[node] == outgoing[node] == 0),
        "highest_fan_in": {"degree": peak_in, "nodes": sorted(labels[node] for node, degree in incoming.items() if degree == peak_in)},
        "highest_fan_out": {"degree": peak_out, "nodes": sorted(labels[node] for node, degree in outgoing.items() if degree == peak_out)},
        "maximum_transitive_reach": {"reachable_nodes": peak_reach, "nodes": sorted(labels[node] for node, count in reach.items() if count == peak_reach)},
        "maximum_call_chain_depth": max(0, len(longest) - 1), "longest_call_chain": longest,
        "maximum_syntactic_call_nesting": maximum_nesting,
        "deepest_nested_call_owners": sorted(labels[node] for node in deepest),
        "recursive_components": sorted([sorted(labels[node] for node in component) for component in recursive_ids]),
        "pagerank_top": _top({labels[node]: score for node, score in pagerank.items()}),
        "betweenness_top": _top({labels[node]: score for node, score in betweenness.items()}),
        "risk_top": risks[:10],
        "node_kinds": dict(sorted(Counter(str(all_nodes[node].get("kind")) for node in call_owner_ids).items())),
    }
