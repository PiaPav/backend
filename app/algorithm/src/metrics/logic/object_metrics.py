"""Object-oriented class metrics derived from the public parser graph."""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from collections.abc import Mapping
from itertools import combinations
from typing import Any
from .identity import graph_files, legacy_file_id
from .complexity import canonical_callable_metrics
from .projections import MetricsGraphProjection, iter_legacy_calls


BUILTIN_TYPES = {
    "Any", "None", "bool", "bytes", "dict", "float", "int", "list",
    "object", "set", "str", "tuple", "Optional", "Union", "Literal",
}


def _type_names(value: Any) -> set[str]:
    if isinstance(value, str):
        current = ""
        result: set[str] = set()
        for char in value:
            if char.isalnum() or char in "_.":
                current += char
            elif current:
                result.add(current)
                current = ""
        if current:
            result.add(current)
        return {name.rsplit(".", 1)[-1] for name in result} - BUILTIN_TYPES
    if isinstance(value, Mapping):
        return set().union(*(_type_names(item) for item in value.values()))
    if isinstance(value, (list, tuple)):
        return set().union(*(_type_names(item) for item in value))
    return set()


def _call_names(calls: Any) -> set[str]:
    return {
        name
        for item in iter_legacy_calls(calls if isinstance(calls, (list, tuple)) else ())
        if (name := str(item.call.get("object") or ""))
    }


def _top(rows: list[dict[str, Any]], key: str, *, reverse: bool = True) -> list[dict[str, Any]]:
    filtered = [row for row in rows if row.get(key) is not None]
    return sorted(
        filtered,
        key=lambda row: ((-row[key]) if reverse else row[key], row["class"]),
    )[:10]


def calculate_object_metrics(
    graph: Mapping[str, Any], *, cyclic_dit_is_none: bool = False,
    projection: MetricsGraphProjection | None = None,
) -> dict[str, Any]:
    classes: list[tuple[str, str, Mapping[str, Any]]] = []
    files = [file.data for file in projection.legacy_files] if projection else graph_files(graph)
    for file in files:
        module = legacy_file_id(file)
        for class_info in file.get("classes", []):
            if isinstance(class_info, Mapping):
                name = str(class_info.get("name"))
                classes.append((f"{module}.{name}", module, class_info))

    by_short: dict[str, list[str]] = {}
    for qualified, _, class_info in classes:
        by_short.setdefault(str(class_info.get("name")), []).append(qualified)
    class_names = {qualified for qualified, _, _ in classes}

    def resolve(name: str, module: str) -> str | None:
        if "." in name:
            # A qualified external/imported base must never bind to an unrelated
            # local class merely because its final component happens to match.
            return name if name in class_names else None
        short = name.rsplit(".", 1)[-1]
        local = f"{module}.{short}"
        if local in class_names:
            return local
        matches = by_short.get(short, [])
        return matches[0] if len(matches) == 1 else None

    parents: dict[str, set[str]] = {}
    children: Counter[str] = Counter()
    for qualified, module, class_info in classes:
        raw = class_info.get("parent")
        parent_names = raw if isinstance(raw, (list, tuple)) else ([raw] if raw else [])
        parents[qualified] = {
            resolved
            for name in parent_names
            if (resolved := resolve(str(name), module)) is not None
        }
        children.update(parents[qualified])

    def legacy_inheritance_depth(name: str, visiting: set[str] | None = None) -> int | None:
        visiting = visiting or set()
        if name in visiting:
            return 0
        if not parents.get(name):
            return 0
        depths = [legacy_inheritance_depth(parent, visiting | {name}) for parent in parents[name]]
        return 1 + max(depths)  # type: ignore[arg-type]

    depths: dict[str, int | None] = {}
    if cyclic_dit_is_none:
        # Explicit DFS frames avoid Python recursion limits.  A repeated active
        # node poisons the cycle and every class that depends on it.
        for root in sorted(parents):
            if root in depths: continue
            active: set[str] = set(); stack = [(root, False)]
            while stack:
                name, complete = stack.pop()
                if name in depths: continue
                if complete:
                    active.discard(name)
                    values = [depths[parent] for parent in parents.get(name, ())]
                    depths[name] = None if any(value is None for value in values) else (1 + max(values) if values else 0)  # type: ignore[arg-type]
                    continue
                if name in active:
                    depths[name] = None
                    continue
                active.add(name); stack.append((name, True))
                for parent in sorted(parents.get(name, ()), reverse=True):
                    if parent in active:
                        depths[parent] = None
                    elif parent not in depths:
                        stack.append((parent, False))

    rows: list[dict[str, Any]] = []
    for qualified, module, class_info in classes:
        methods = [item for item in class_info.get("methods", []) if isinstance(item, Mapping)]
        fields = {
            str(item.get("name"))
            for item in class_info.get("fields", [])
            if isinstance(item, Mapping)
        }
        weighted_methods = sum(
            int(method.get("metrics", {}).get("cyclomatic_complexity", 1))
            for method in methods
        )
        response = set().union(*(_call_names(method.get("calls", [])) for method in methods))
        dependencies = set(parents[qualified])
        for field in class_info.get("fields", []):
            if isinstance(field, Mapping):
                for type_name in _type_names(field.get("type")):
                    if target := resolve(type_name, module):
                        dependencies.add(target)
        for call_name in response:
            if target := resolve(call_name.split(".", 1)[0], module):
                dependencies.add(target)
        dependencies.discard(qualified)

        method_fields = [
            set(map(str, method.get("metrics", {}).get("self_attribute_accesses", [])))
            & fields
            for method in methods
        ]
        pairs = list(combinations(method_fields, 2))
        lack_of_cohesion = (
            sum(not (left & right) for left, right in pairs) / len(pairs)
            if pairs and fields
            else None
        )
        rows.append(
            {
                "class": qualified,
                "wmc": weighted_methods,
                "cbo": len(dependencies),
                "rfc": len(methods) + len(response),
                "lcom": round(lack_of_cohesion, 4) if lack_of_cohesion is not None else None,
                "dit": depths.get(qualified) if cyclic_dit_is_none else legacy_inheritance_depth(qualified),
                "noc": children[qualified],
            }
        )

    result = {
        "classes_analyzed": len(rows),
        "highest_weighted_method_complexity": _top(rows, "wmc"),
        "highest_class_coupling": _top(rows, "cbo"),
        "largest_response_sets": _top(rows, "rfc"),
        "lowest_cohesion": _top(rows, "lcom"),
        "deepest_inheritance": _top(rows, "dit"),
        "most_direct_children": _top(rows, "noc"),
    }
    if cyclic_dit_is_none:
        result["classes"] = sorted(rows, key=lambda row: row["class"])
    return result


def calculate_canonical_object_metrics(
    graph: Mapping[str, Any], *, projection: MetricsGraphProjection | None = None,
    wmc_by_class_id: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    """Calculate object metrics exclusively from canonical ID relations."""
    projection = projection or MetricsGraphProjection.from_graph(graph)
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
        callable_metrics = canonical_callable_metrics(graph, projection=projection)
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


def calculate_semantics_v2_object_metrics(
    graph: Mapping[str, Any], *, projection: MetricsGraphProjection | None = None,
) -> dict[str, Any]:
    """Compatibility adapter for the semantics-v2 body-derived WMC."""
    projection = projection or MetricsGraphProjection.from_graph(graph)
    legacy_wmc: dict[tuple[str, str], deque[int]] = defaultdict(deque)
    for legacy_file in projection.legacy_files:
        file = legacy_file.data
        path_parts = tuple(str(part) for part in file.get("path_parts", ()))
        source_path = "/".join((*path_parts, f"{file.get('name')}.py"))
        for class_info in file.get("classes", []):
            if not isinstance(class_info, Mapping):
                continue
            class_name = str(class_info.get("name") or "")
            legacy_wmc[(source_path, class_name)].append(sum(
                int(method.get("metrics", {}).get("cyclomatic_complexity", 1))
                for method in class_info.get("methods", [])
                if isinstance(method, Mapping)
            ))

    def source_occurrence(item: tuple[str, Mapping[str, Any]]) -> tuple[str, int, int, str]:
        identifier, node = item
        location = node.get("location")
        if not isinstance(location, Mapping):
            location = {}
        path = str(node.get("path") or location.get("path") or "")
        line = location.get("line")
        column = location.get("column")
        return (
            path,
            int(line) if isinstance(line, int) else 2**63 - 1,
            int(column) if isinstance(column, int) else 2**63 - 1,
            identifier,
        )

    canonical_classes = sorted(
        (
            (identifier, node)
            for identifier, node in projection.nodes_by_id.items()
            if node.get("kind") == "class"
        ),
        key=source_occurrence,
    )
    wmc_by_class_id: dict[str, int] = {}
    for identifier, node in canonical_classes:
        class_name = str(node.get("qualified_name") or identifier).rsplit(".", 1)[-1]
        occurrences = legacy_wmc.get((str(node.get("path") or ""), class_name))
        wmc_by_class_id[identifier] = occurrences.popleft() if occurrences else 0
    return calculate_canonical_object_metrics(
        graph, projection=projection, wmc_by_class_id=wmc_by_class_id,
    )
