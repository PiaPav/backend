"""Object-oriented class metrics derived from the public parser graph."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from itertools import combinations
from typing import Any
from .identity import graph_files, legacy_file_id


BUILTIN_TYPES = {
    "Any", "None", "bool", "bytes", "dict", "float", "int", "list",
    "object", "set", "str", "tuple", "Optional", "Union", "Literal",
}


def _file_id(file: Mapping[str, Any]) -> str:
    return legacy_file_id(file)


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
    if isinstance(value, list):
        return set().union(*(_type_names(item) for item in value))
    return set()


def _call_names(calls: Any) -> set[str]:
    result: set[str] = set()
    for call in calls if isinstance(calls, list) else []:
        if not isinstance(call, Mapping):
            continue
        name = str(call.get("object") or "")
        if name:
            result.add(name)
        for argument in call.get("args", []):
            if isinstance(argument, Mapping):
                value = argument.get("value")
                if isinstance(value, Mapping) and value.get("type") == "call":
                    result |= _call_names([value])
    return result


def _top(rows: list[dict[str, Any]], key: str, *, reverse: bool = True) -> list[dict[str, Any]]:
    filtered = [row for row in rows if row.get(key) is not None]
    return sorted(
        filtered,
        key=lambda row: ((-row[key]) if reverse else row[key], row["class"]),
    )[:10]


def calculate_object_metrics(graph: Mapping[str, Any], *, cyclic_dit_is_none: bool = False) -> dict[str, Any]:
    classes: list[tuple[str, str, Mapping[str, Any]]] = []
    for file in graph_files(graph):
        module = _file_id(file)
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
        parent_names = raw if isinstance(raw, list) else ([raw] if raw else [])
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
