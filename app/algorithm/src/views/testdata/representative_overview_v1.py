"""Immutable source family for the aggregate.overview/1 preflight."""
from __future__ import annotations

from typing import Any

from graph_dto import graph_fingerprint, validate_graph_v1

OVERVIEW_V1_PACKAGE_COUNTS = {"medium": 12, "large": 24}


def _location(path: str, line: int, column: int = 0) -> dict[str, Any]:
    return {"path": path, "line": line, "column": column}


def _complexity(path: str, line: int, column: int = 0) -> dict[str, Any]:
    return {
        "span": {"start": _location(path, line, column),
                 "end": _location(path, line + 2, column + 12)},
        "is_async": False,
        "controls": [{"kind": "if", "parent_index": None,
                      "location": _location(path, line + 1, column + 4),
                      "operand_count": 0, "case_count": 0, "filter_count": 0}],
        "occurrences": [{"kind": "return", "location": _location(path, line + 2, column + 8)}],
    }


def build_representative_overview_v1(size: str) -> dict[str, Any]:
    """Return a fresh schema-1/semantics-7 graph; family composition is frozen."""
    if size not in OVERVIEW_V1_PACKAGE_COUNTS:
        raise ValueError(f"Unsupported representative overview size {size!r}")
    count = OVERVIEW_V1_PACKAGE_COUNTS[size]
    labels = ["<root>", "пакет"] + [f"pkg{i:02d}" for i in range(2, count)]
    graph: dict[str, Any] = {
        "schema_version": 1, "parser_semantics_version": 7,
        "project": {"fingerprint": ""}, "nodes": [], "edges": [],
        "callsites": [], "type_references": [], "import_references": [],
        "owner_structural_facts": [], "diagnostics": [],
    }
    roots: list[tuple[str, str]] = []

    for index, label in enumerate(labels):
        prefix = "" if label == "<root>" else f"{label}/"
        paths = (f"{prefix}source_{index:02d}.py", f"{prefix}target_{index:02d}.py")
        pair: list[str] = []
        for role, path in enumerate(paths):
            root_id = f"file:{path}"
            pair.append(root_id)
            graph["nodes"].append({"id": root_id, "kind": "file", "qualified_name": path[:-3].replace("/", "."),
                                   "parent_id": None, "path": path, "location": _location(path, 1)})
            graph["owner_structural_facts"].append({
                "owner_id": root_id, "call_occurrences": index + role,
                "direct_import_occurrences": {"project_local": 5 + role, "non_project": 2},
            })
        roots.append((pair[0], pair[1]))
        class_kind = ("abstract", "dataclass", "class")[index % 3]
        class_id = f"class:{paths[0]}:10:0:Service{index}"
        function_id = f"function:{paths[0]}:40:0:build_{index}"
        method_id = f"method:{paths[0]}:20:4:Service{index}.run"
        declarations = [
            {"id": class_id, "kind": "class", "class_kind": class_kind, "qualified_name": f"Service{index}",
             "parent_id": pair[0], "path": paths[0], "location": _location(paths[0], 10)},
            {"id": f"field:{paths[0]}:12:4:Service{index}.value", "kind": "field", "qualified_name": f"Service{index}.value",
             "parent_id": class_id, "path": paths[0], "location": _location(paths[0], 12, 4)},
            {"id": method_id, "kind": "method", "qualified_name": f"Service{index}.run",
             "parent_id": class_id, "path": paths[0], "location": _location(paths[0], 20, 4),
             "complexity_facts": _complexity(paths[0], 20, 4)},
            {"id": f"method:{paths[0]}:10:0:Service{index}.__init__", "kind": "method", "synthetic": True,
             "qualified_name": f"Service{index}.__init__", "parent_id": class_id, "path": paths[0], "location": _location(paths[0], 10)},
            {"id": function_id, "kind": "function", "qualified_name": f"build_{index}",
             "parent_id": pair[0], "path": paths[0], "location": _location(paths[0], 40),
             "complexity_facts": _complexity(paths[0], 40)},
            {"id": f"constant:{paths[1]}:5:0:LIMIT:{index}", "kind": "constant", "qualified_name": "LIMIT",
             "parent_id": pair[1], "path": paths[1], "location": _location(paths[1], 5)},
        ]
        graph["nodes"].extend(declarations)
        for node in declarations:
            graph["edges"].append({"id": f"contains:{node['id']}", "kind": "contains",
                                   "source_id": node["parent_id"], "target_id": node["id"]})
        graph["owner_structural_facts"].extend([
            {"owner_id": function_id, "call_occurrences": 7},
            {"owner_id": method_id, "call_occurrences": 11},
        ])

    import_ordinal = 0
    def add_import(source: str, target: str | None, status: str, line: int) -> None:
        nonlocal import_ordinal
        import_ordinal += 1
        path = source.removeprefix("file:")
        identifier = f"import:{import_ordinal}"
        ref = {"id": identifier, "importer_id": source, "kind": "from", "module": "fixture", "name": "item",
               "alias": None, "level": 1 if status == "unresolved" else 0,
               "location": _location(path, line), "resolution": status,
               "target_id": target, "candidate_ids": []}
        graph["import_references"].append(ref)
        if status == "exact":
            graph["edges"].append({"id": f"imports:{identifier}", "kind": "imports",
                                   "source_id": source, "target_id": target, "location": ref["location"]})

    for index, (source, target) in enumerate(roots):
        if index == len(roots) - 1:
            continue  # the final package and both roots are topology-isolated
        add_import(source, source, "exact", 2)                 # self
        add_import(source, target, "exact", 3)                 # within package
        add_import(source, target, "exact", 4)                 # repeated pair
        add_import(source, None, "external", 5)
        add_import(source, None, "unresolved", 6)
        if index:
            add_import(source, roots[index - 1][1], "exact", 7)  # >10 tied fan-in/out candidates
    # A quotient cycle whose three cross-package edges do not form a file SCC.
    add_import(roots[0][0], roots[1][0], "exact", 8)
    add_import(roots[1][1], roots[2][0], "exact", 8)
    add_import(roots[2][1], roots[0][1], "exact", 8)
    # A distinct file SCC, entirely inside the penultimate package, plus reverse import.
    add_import(roots[-2][1], roots[-2][0], "exact", 9)
    # Boundary tie for both file fan-in and fan-out rankings.
    add_import(roots[1][1], roots[-2][1], "exact", 10)

    call_statuses = ("exact", "ambiguous", "external", "dynamic", "unresolved")
    type_statuses = ("exact", "ambiguous", "external", "unresolved")
    for index, (source, _) in enumerate(roots):
        path = source.removeprefix("file:")
        class_id = f"class:{path}:10:0:Service{index}"
        method_id = f"method:{path}:20:4:Service{index}.run"
        next_path = roots[(index + 1) % len(roots)][0].removeprefix("file:")
        next_class_id = f"class:{next_path}:10:0:Service{(index + 1) % len(roots)}"
        for offset, status in enumerate(call_statuses):
            graph["callsites"].append({"id": f"call:{index}:{status}", "caller_id": method_id,
                "expression": status, "location": _location(path, 21 + offset, 8), "syntactic_depth": 0,
                "resolution": status, "target_id": method_id if status == "exact" else None,
                "candidate_ids": sorted([method_id, f"function:{path}:40:0:build_{index}"]) if status == "ambiguous" else [],
                "awaited": False})
        graph["edges"].append({"id": f"calls:{index}:non-awaited", "kind": "calls",
                               "source_id": method_id, "target_id": method_id, "weight": 1})
        graph["edges"].append({"id": f"inherits:{index}:exact", "kind": "inherits",
                               "source_id": class_id, "target_id": class_id})
        for offset, status in enumerate(type_statuses):
            graph["type_references"].append({"id": f"type:{index}:{status}", "owner_id": class_id,
                "role": "base", "expression": status, "location": _location(path, 30 + offset),
                "resolution": status, "target_id": class_id if status == "exact" else None,
                "candidate_ids": sorted([class_id, next_class_id]) if status == "ambiguous" else []})

    graph["project"]["fingerprint"] = graph_fingerprint(graph)
    validate_graph_v1(graph)
    return graph


__all__ = ["OVERVIEW_V1_PACKAGE_COUNTS", "build_representative_overview_v1"]
