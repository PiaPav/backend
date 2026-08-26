"""Function- and method-level call graph construction and metrics."""

from __future__ import annotations

from collections import Counter, deque
from collections.abc import Mapping
from typing import Any

from .quality import callable_metrics


BUILTIN_CALLS = {
    "all", "any", "bool", "bytes", "dict", "enumerate", "filter", "float",
    "format", "getattr", "hasattr", "int", "isinstance", "iter", "len", "list",
    "map", "max", "min", "next", "object", "open", "print", "range", "repr",
    "reversed", "round", "set", "setattr", "sorted", "str", "sum", "super",
    "tuple", "type", "zip",
}


def _file_id(file: Mapping[str, Any]) -> str:
    path = str(file.get("path") or "")
    name = str(file.get("name") or "unknown")
    return path or name if name == "__init__" else ".".join(filter(None, (path, name)))


def _graph_files(graph: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        dict(wrapper["file"])
        for wrapper in graph.get("body", [])
        if isinstance(wrapper, Mapping) and isinstance(wrapper.get("file"), Mapping)
    ]


def _nested_calls(call: Mapping[str, Any], depth: int = 1):
    yield call, depth
    for argument in call.get("args", []):
        if not isinstance(argument, Mapping):
            continue
        value = argument.get("value")
        if isinstance(value, Mapping) and value.get("type") == "call":
            yield from _nested_calls(value, depth + 1)


def _strong_components(nodes: set[str], edges: set[tuple[str, str]]) -> list[set[str]]:
    adjacency = {node: set() for node in nodes}
    for source, target in edges:
        adjacency[source].add(target)
    index = 0
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    result: list[set[str]] = []

    def visit(node: str) -> None:
        nonlocal index
        indices[node] = lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for target in adjacency[node]:
            if target not in indices:
                visit(target)
                lowlinks[node] = min(lowlinks[node], lowlinks[target])
            elif target in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[target])
        if lowlinks[node] != indices[node]:
            return
        component: set[str] = set()
        while True:
            target = stack.pop()
            on_stack.remove(target)
            component.add(target)
            if target == node:
                break
        result.append(component)

    for node in sorted(nodes):
        if node not in indices:
            visit(node)
    return result


def _longest_component_path(
    components: list[set[str]], edges: set[tuple[str, str]]
) -> list[str]:
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

    def longest(start: int) -> list[int]:
        if start not in cache:
            tails = [longest(target) for target in adjacency[start]]
            cache[start] = [start, *(max(tails, key=len) if tails else [])]
        return cache[start]

    path = max((longest(index) for index in adjacency), key=len)
    return [
        next(iter(components[index]))
        if len(components[index]) == 1
        else "{" + " ↔ ".join(sorted(components[index])) + "}"
        for index in path
    ]


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


def calculate_call_graph_metrics(graph: Mapping[str, Any]) -> dict[str, Any]:
    """Build a qualified call graph and calculate vertex-oriented metrics."""
    files = _graph_files(graph)
    nodes: set[str] = set()
    kinds: dict[str, str] = {}
    local_symbols: dict[tuple[str, str], str] = {}
    imports: dict[str, dict[str, tuple[str, str]]] = {}
    external_roots: dict[str, set[str]] = {}
    owners: list[tuple[str, str, str | None, list[Any]]] = []

    for file in files:
        module = _file_id(file)
        imports[module] = {}
        external_roots[module] = set()
        for imported in file.get("imports", []):
            if not isinstance(imported, Mapping):
                continue
            original = str(imported.get("object") or "")
            local_names = {original, str(imported.get("asname") or original)}
            if imported.get("from_lib") is True:
                external_roots[module].update(local_names)
                external_roots[module].add(str(imported.get("path") or "").split(".", 1)[0])
                continue
            if imported.get("from_lib") is not False:
                continue
            target_module = str(imported.get("path") or "")
            for local_name in local_names:
                imports[module][local_name] = (target_module, original)
        if file.get("calls"):
            module_node = f"{module}.__module__"
            nodes.add(module_node)
            kinds[module_node] = "module"
            owners.append((module_node, module, None, file.get("calls", [])))
        for function in file.get("functions", []):
            if not isinstance(function, Mapping):
                continue
            qualified = f"{module}.{function.get('name')}"
            nodes.add(qualified)
            kinds[qualified] = "function"
            local_symbols[(module, str(function.get("name")))] = qualified
            owners.append((qualified, module, None, function.get("calls", [])))
        for class_info in file.get("classes", []):
            if not isinstance(class_info, Mapping):
                continue
            class_name = str(class_info.get("name"))
            method_names: set[str] = set()
            for method in class_info.get("methods", []):
                if not isinstance(method, Mapping):
                    continue
                method_name = str(method.get("name"))
                method_names.add(method_name)
                qualified = f"{module}.{class_name}.{method_name}"
                nodes.add(qualified)
                kinds[qualified] = "method"
                local_symbols[(module, f"{class_name}.{method_name}")] = qualified
                owners.append((qualified, module, class_name, method.get("calls", [])))
            if "__init__" not in method_names:
                qualified = f"{module}.{class_name}.__init__"
                nodes.add(qualified)
                kinds[qualified] = "implicit_constructor"
                local_symbols[(module, f"{class_name}.__init__")] = qualified

    suffix_index: dict[str, list[str]] = {}
    for node in nodes:
        parts = node.split(".")
        for size in (1, 2, 3):
            if len(parts) >= size:
                suffix_index.setdefault(".".join(parts[-size:]), []).append(node)

    def resolve(name: str, module: str, owner: str | None) -> str | None:
        if not name:
            return None
        if name.startswith("self.") and owner:
            candidate = local_symbols.get((module, f"{owner}.{name[5:]}"))
            if candidate:
                return candidate
        candidate = local_symbols.get((module, name))
        if candidate:
            return candidate
        parts = name.split(".")
        imported = imports.get(module, {}).get(parts[0])
        if imported:
            target_module, original = imported
            imported_name = ".".join([original, *parts[1:]])
            candidate = local_symbols.get((target_module, imported_name))
            if candidate:
                return candidate
        matches = suffix_index.get(name, [])
        return matches[0] if len(matches) == 1 else None

    edge_weights: Counter[tuple[str, str]] = Counter()
    unresolved_local = 0
    external = 0
    maximum_nesting = 0
    deepest_owners: set[str] = set()
    for caller, module, owner, calls in owners:
        for raw_call in calls:
            if not isinstance(raw_call, Mapping):
                continue
            for call, depth in _nested_calls(raw_call):
                if depth > maximum_nesting:
                    maximum_nesting = depth
                    deepest_owners = {caller}
                elif depth == maximum_nesting:
                    deepest_owners.add(caller)
                target = resolve(str(call.get("object") or ""), module, owner)
                if target:
                    edge_weights[(caller, target)] += 1
                else:
                    name = str(call.get("object") or "")
                    root = name.split(".", 1)[0]
                    if root in external_roots.get(module, set()) or root in BUILTIN_CALLS:
                        external += 1
                    else:
                        unresolved_local += 1

    edges = set(edge_weights)
    incoming = {node: 0 for node in nodes}
    outgoing = {node: 0 for node in nodes}
    adjacency = {node: set() for node in nodes}
    for source, target in edges:
        outgoing[source] += 1
        incoming[target] += 1
        adjacency[source].add(target)
    components = _strong_components(nodes, edges)
    recursive = [
        sorted(component)
        for component in components
        if len(component) > 1 or any((node, node) in edges for node in component)
    ]
    longest_chain = _longest_component_path(components, edges)

    reach = {}
    for start in nodes:
        visited: set[str] = set()
        pending = list(adjacency[start])
        while pending:
            node = pending.pop()
            if node in visited:
                continue
            visited.add(node)
            pending.extend(adjacency[node] - visited)
        visited.discard(start)
        reach[start] = len(visited)

    peak_in = max(incoming.values(), default=0)
    peak_out = max(outgoing.values(), default=0)
    peak_reach = max(reach.values(), default=0)
    pagerank = _pagerank(nodes, edges)
    betweenness = _betweenness(nodes, edges)
    complexity = callable_metrics(graph)
    complexity_raw = {
        node: max(0, int(item.get("cyclomatic_complexity", 1)) - 1)
        + int(item.get("cognitive_complexity", 0))
        for node, item in complexity.items()
    }
    peak_complexity = max(complexity_raw.values(), default=0)
    peak_betweenness = max(betweenness.values(), default=0.0)
    risks = []
    for node in nodes:
        complexity_factor = complexity_raw.get(node, 0) / peak_complexity if peak_complexity else 0.0
        fan_in_factor = incoming[node] / peak_in if peak_in else 0.0
        bridge_factor = betweenness[node] / peak_betweenness if peak_betweenness else 0.0
        reach_factor = reach[node] / peak_reach if peak_reach else 0.0
        score = 100 * (
            0.35 * complexity_factor
            + 0.25 * fan_in_factor
            + 0.20 * bridge_factor
            + 0.20 * reach_factor
        )
        if score:
            risks.append(
                {
                    "node": node,
                    "score": round(score, 2),
                    "cyclomatic": int(complexity.get(node, {}).get("cyclomatic_complexity", 0)),
                    "cognitive": int(complexity.get(node, {}).get("cognitive_complexity", 0)),
                    "fan_in": incoming[node],
                    "betweenness": round(betweenness[node], 6),
                    "transitive_reach": reach[node],
                }
            )
    risks.sort(key=lambda item: (-item["score"], item["node"]))
    local_callsites = sum(edge_weights.values())
    total_callsites = local_callsites + external + unresolved_local

    return {
        "nodes": len(nodes),
        "edges": len(edges),
        "callsites_in_local_edges": local_callsites,
        "external_or_builtin_callsites": external,
        "unresolved_callsites": unresolved_local,
        "unresolved_or_external_callsites": external + unresolved_local,
        "local_resolution_rate": round(local_callsites / total_callsites, 4)
        if total_callsites
        else 0.0,
        "classified_callsite_rate": round(
            (local_callsites + external) / total_callsites, 4
        )
        if total_callsites
        else 0.0,
        "heaviest_edges": [
            {"caller": source, "target": target, "callsites": weight}
            for (source, target), weight in sorted(
                edge_weights.items(), key=lambda item: (-item[1], item[0])
            )[:10]
        ],
        "entrypoints": sorted(
            node for node in nodes if incoming[node] == 0 and outgoing[node] > 0
        ),
        "leaf_callables": sorted(
            node for node in nodes if incoming[node] > 0 and outgoing[node] == 0
        ),
        "isolated_callables": sorted(
            node for node in nodes if incoming[node] == outgoing[node] == 0
        ),
        "highest_fan_in": {
            "degree": peak_in,
            "nodes": sorted(node for node, degree in incoming.items() if degree == peak_in),
        },
        "highest_fan_out": {
            "degree": peak_out,
            "nodes": sorted(node for node, degree in outgoing.items() if degree == peak_out),
        },
        "maximum_transitive_reach": {
            "reachable_nodes": peak_reach,
            "nodes": sorted(node for node, count in reach.items() if count == peak_reach),
        },
        "maximum_call_chain_depth": max(0, len(longest_chain) - 1),
        "longest_call_chain": longest_chain,
        "maximum_syntactic_call_nesting": maximum_nesting,
        "deepest_nested_call_owners": sorted(deepest_owners) if maximum_nesting else [],
        "recursive_components": recursive,
        "pagerank_top": _top(pagerank),
        "betweenness_top": _top(betweenness),
        "risk_top": risks[:10],
        "node_kinds": dict(sorted(Counter(kinds.values()).items())),
    }
