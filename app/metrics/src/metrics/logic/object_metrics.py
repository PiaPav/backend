"""Object-oriented class metrics derived from the public parser graph."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from itertools import combinations
from typing import Any
from .complexity import canonical_callable_metrics
from .projections import MetricsGraphProjection


def _top(rows: list[dict[str, Any]], key: str, *, reverse: bool = True) -> list[dict[str, Any]]:
    filtered = [row for row in rows if row.get(key) is not None]
    return sorted(
        filtered,
        key=lambda row: ((-row[key]) if reverse else row[key], row["class"]),
    )[:10]


def calculate_object_metrics(
    graph: Mapping[str, Any], *, projection: MetricsGraphProjection | None = None,
) -> dict[str, Any]:
    """Canonical gateway for object metrics."""
    if projection is None:
        from .calculator import validate_metrics_graph
        validate_metrics_graph(graph)
        projection = MetricsGraphProjection.from_graph(graph)
    return _calculate_canonical_object_metrics(projection)


def _calculate_canonical_object_metrics(
    projection: MetricsGraphProjection, *,
    wmc_by_class_id: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    """Calculate object metrics exclusively from canonical ID relations."""
    nodes = projection.nodes_by_id
    class_ids = set(projection.node_ids_by_kind.get("class", ()))
    method_ids = set(projection.node_ids_by_kind.get("method", ()))
    field_ids = set(projection.node_ids_by_kind.get("field", ()))
    parents = {identifier: set() for identifier in class_ids}
    children = {identifier: set() for identifier in class_ids}
    fields_by_class = {identifier: set() for identifier in class_ids}
    methods_by_class = {identifier: set() for identifier in class_ids}
    field_types = {identifier: set() for identifier in field_ids}
    accesses = {identifier: set() for identifier in method_ids}
    calls = {identifier: set() for identifier in method_ids}

    base_labels = {
        identifier: str(nodes[identifier].get("qualified_name") or identifier)
        for identifier in class_ids
    }
    label_counts = Counter(base_labels.values())
    labels = {
        identifier: (
            label if label_counts[label] == 1 else f"{label} [{identifier}]"
        )
        for identifier, label in base_labels.items()
    }

    for identifier in field_ids:
        owner = nodes[identifier].get("parent_id")
        if owner in class_ids: fields_by_class[owner].add(identifier)
    for identifier in method_ids:
        owner = nodes[identifier].get("parent_id")
        if owner in class_ids: methods_by_class[owner].add(identifier)
    for source, target in projection.directed_canonical_inheritance_graph.edges:
        parents[source].add(target)
        if source != target:
            children[target].add(source)
    for source, target in projection.directed_canonical_field_type_graph.edges:
        field_types[source].add(target)
    for source, target in projection.directed_canonical_field_access_graph.edges:
        accesses[source].add(target)
    for source, target in projection.directed_canonical_call_graph.edges:
        if source in method_ids and target in nodes and nodes[target].get("kind") in {"function", "method"}:
            calls[source].add(target)

    depths: dict[str, int | None] = {}
    for root in sorted(class_ids):
        if root in depths: continue
        active: set[str] = set(); stack = [(root, False)]
        while stack:
            current, complete = stack.pop()
            if current in depths: continue
            if complete:
                active.discard(current)
                values = [depths[parent] for parent in parents[current]]
                depths[current] = None if any(value is None for value in values) else (1 + max(values) if values else 0)  # type: ignore[arg-type]
                continue
            if current in active:
                depths[current] = None; continue
            active.add(current); stack.append((current, True))
            for parent in sorted(parents[current], reverse=True):
                if parent in active: depths[parent] = None
                elif parent not in depths: stack.append((parent, False))

    if wmc_by_class_id is None:
        callable_metrics = canonical_callable_metrics(projection)
        wmc_by_class_id = {
            class_id: sum(
                int(callable_metrics[method]["cyclomatic_complexity"])
                for method in methods_by_class[class_id]
                if method in callable_metrics and not bool(nodes[method].get("synthetic"))
            )
            for class_id in class_ids
        }

    rows = []
    for class_id in class_ids:
        node = nodes[class_id]; label = labels[class_id]
        declared = {
            method for method in methods_by_class[class_id]
            if not bool(nodes[method].get("synthetic"))
        }
        dependencies = set(parents[class_id])
        for field in fields_by_class[class_id]: dependencies.update(field_types[field])
        targets = set().union(*(calls[method] for method in declared)) if declared else set()
        for target in targets:
            owner = nodes[target].get("parent_id")
            if owner in class_ids: dependencies.add(owner)
        dependencies.discard(class_id)
        method_fields = [accesses[method] & fields_by_class[class_id] for method in declared]
        pairs = list(combinations(method_fields, 2))
        lcom = (sum(not (left & right) for left, right in pairs) / len(pairs)) if pairs and fields_by_class[class_id] else None
        wmc = int(wmc_by_class_id.get(class_id, 0))
        rows.append({
            "class": label, "wmc": wmc, "cbo": len(dependencies),
            "rfc": len(declared | targets), "lcom": round(lcom, 4) if lcom is not None else None,
            "dit": depths[class_id], "noc": len(children[class_id]),
        })
    result = {
        "classes_analyzed": len(rows),
        "highest_weighted_method_complexity": _top(rows, "wmc"),
        "highest_class_coupling": _top(rows, "cbo"),
        "largest_response_sets": _top(rows, "rfc"),
        "lowest_cohesion": _top(rows, "lcom"),
        "deepest_inheritance": _top(rows, "dit"),
        "most_direct_children": _top(rows, "noc"),
        "classes": sorted(rows, key=lambda row: row["class"]),
    }
    return result


def calculate_canonical_object_metrics(
    graph: Mapping[str, Any], *, projection: MetricsGraphProjection | None = None,
) -> dict[str, Any]:
    """Canonical gateway for object metrics."""
    if projection is None:
        from .calculator import validate_metrics_graph
        validate_metrics_graph(graph)
        projection = MetricsGraphProjection.from_graph(graph)
    return _calculate_canonical_object_metrics(projection)
