"""Predeclared representative Graph DTO benchmark family v2."""
from __future__ import annotations

from typing import Any

from graph_dto import graph_fingerprint, validate_graph_v1

_SIZES = {"medium": 4, "large": 10}


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


def build_representative_graph_v2(size: str) -> dict[str, Any]:
    """Build medium or large v2 with every non-declaration population scaling by n."""
    if size not in _SIZES:
        raise ValueError(f"Unsupported representative graph size {size!r}")
    count = _SIZES[size]
    graph: dict[str, Any] = {
        "schema_version": 1, "parser_semantics_version": 7,
        "project": {"fingerprint": ""}, "nodes": [], "edges": [],
        "callsites": [], "type_references": [], "import_references": [],
        "owner_structural_facts": [], "diagnostics": [],
    }
    nodes, edges = graph["nodes"], graph["edges"]
    module_id = "module:benchmark.service"
    module_path = "benchmark/service.py"
    nodes.append({"id": module_id, "kind": "module", "qualified_name": "benchmark.service",
                  "parent_id": None, "path": module_path, "location": _location(module_path, 1)})
    graph["owner_structural_facts"].append({
        "owner_id": module_id, "call_occurrences": 0,
        "direct_import_occurrences": {"project_local": 0, "non_project": 0},
    })

    components: list[dict[str, str]] = []
    for ordinal in range(1, count + 1):
        number = f"{ordinal:02d}"
        path = f"benchmark/component_{number}.py"
        ids = {
            "file": f"file:{path}", "class": f"class:{path}:10:0:Component{number}",
            "field": f"field:{path}:12:4:Component{number}.value",
            "synthetic": f"method:{path}:10:0:Component{number}.__init__",
            "method": f"method:{path}:20:4:Component{number}.run",
            "function": f"function:{path}:40:0:build_{number}",
            "constant": f"constant:{path}:5:0:LIMIT_{number}:1", "path": path,
        }
        components.append(ids)
        nodes.extend([
            {"id": ids["file"], "kind": "file", "qualified_name": f"benchmark.component_{number}",
             "parent_id": None, "path": path, "location": _location(path, 1)},
            {"id": ids["class"], "kind": "class", "class_kind": "class",
             "qualified_name": f"benchmark.component_{number}.Component{number}",
             "parent_id": ids["file"], "path": path, "location": _location(path, 10)},
            {"id": ids["field"], "kind": "field",
             "qualified_name": f"benchmark.component_{number}.Component{number}.value",
             "parent_id": ids["class"], "path": path, "location": _location(path, 12, 4)},
            {"id": ids["synthetic"], "kind": "method", "synthetic": True,
             "qualified_name": f"benchmark.component_{number}.Component{number}.__init__",
             "parent_id": ids["class"], "path": path, "location": _location(path, 10)},
            {"id": ids["method"], "kind": "method",
             "qualified_name": f"benchmark.component_{number}.Component{number}.run",
             "parent_id": ids["class"], "path": path, "location": _location(path, 20, 4),
             "complexity_facts": _complexity(path, 20, 4)},
            {"id": ids["function"], "kind": "function",
             "qualified_name": f"benchmark.component_{number}.build_{number}",
             "parent_id": ids["file"], "path": path, "location": _location(path, 40),
             "complexity_facts": _complexity(path, 40)},
            {"id": ids["constant"], "kind": "constant",
             "qualified_name": f"benchmark.component_{number}.LIMIT_{number}",
             "parent_id": ids["file"], "path": path, "location": _location(path, 5)},
        ])
        for child in (ids["class"], ids["function"], ids["constant"]):
            edges.append({"id": f"contains:{child}", "kind": "contains",
                          "source_id": ids["file"], "target_id": child})
        for child in (ids["field"], ids["synthetic"], ids["method"]):
            edges.append({"id": f"contains:{child}", "kind": "contains",
                          "source_id": ids["class"], "target_id": child})
        graph["owner_structural_facts"].extend([
            {"owner_id": ids["file"], "call_occurrences": 0,
             "direct_import_occurrences": {"project_local": 1, "non_project": 2}},
            {"owner_id": ids["method"], "call_occurrences": 5},
            {"owner_id": ids["function"], "call_occurrences": 0},
        ])

    call_statuses = ("exact", "ambiguous", "external", "dynamic", "unresolved")
    for index, ids in enumerate(components):
        next_ids = components[(index + 1) % count]
        prefix = f"{index + 1:02d}"
        for offset, status in enumerate(call_statuses):
            call = {"id": f"call:{prefix}:{status}", "caller_id": ids["method"],
                    "expression": f"invoke_{status}()", "location": _location(ids["path"], 21 + offset, 8),
                    "syntactic_depth": 0, "resolution": status,
                    "target_id": next_ids["method"] if status == "exact" else None,
                    "candidate_ids": sorted([ids["function"], next_ids["method"]]) if status == "ambiguous" else [],
                    "awaited": False}
            graph["callsites"].append(call)
        edges.append({"id": f"calls:{prefix}", "kind": "calls", "source_id": ids["method"],
                      "target_id": next_ids["method"], "weight": 1})

        import_specs = (("exact", "from", "benchmark", f"component_{(index + 1) % count + 1:02d}", 0, next_ids["file"]),
                        ("external", "import", "", "requests", 0, None),
                        ("unresolved", "from", "missing", "adapter", 1, None))
        for offset, (status, kind, module, name, level, target) in enumerate(import_specs):
            identifier = f"import:{prefix}:{status}"
            location = _location(ids["path"], 2 + offset)
            graph["import_references"].append({
                "id": identifier, "importer_id": ids["file"], "kind": kind, "module": module,
                "name": name, "alias": None, "level": level, "location": location,
                "resolution": status, "target_id": target, "candidate_ids": [],
            })
            if status == "exact":
                edges.append({"id": f"imports:{identifier}", "kind": "imports",
                              "source_id": ids["file"], "target_id": target, "location": location})

        type_specs = (("exact", ids["field"], "field_type", next_ids["class"], []),
                      ("ambiguous", ids["class"], "base", None,
                       sorted([ids["class"], next_ids["class"]])),
                      ("external", ids["class"], "base", None, []),
                      ("unresolved", ids["class"], "base", None, []))
        for offset, (status, owner, role, target, candidates) in enumerate(type_specs):
            graph["type_references"].append({
                "id": f"type:{prefix}:{status}", "owner_id": owner, "role": role,
                "expression": f"Type{offset}", "location": _location(ids["path"], 12 + offset, 8),
                "resolution": status, "target_id": target, "candidate_ids": candidates,
            })
        edges.extend([
            {"id": f"field_type:{prefix}", "kind": "field_type",
             "source_id": ids["field"], "target_id": next_ids["class"]},
            {"id": f"accesses_field:{prefix}", "kind": "accesses_field",
             "source_id": ids["method"], "target_id": ids["field"],
             "location": _location(ids["path"], 28, 8)},
        ])
        graph["diagnostics"].extend([
            {"id": f"diagnostic:{prefix}:import", "kind": "import_resolution", "status": "warning",
             "message": "Unresolved local import"},
            {"id": f"diagnostic:{prefix}:call", "kind": "call_resolution", "status": "info",
             "message": "Dynamic call"},
        ])

    graph["project"]["fingerprint"] = graph_fingerprint(graph)
    validate_graph_v1(graph)
    return graph


__all__ = ["build_representative_graph_v2"]
