"""Deterministic Metrics benchmark family v2 and its exact fixture tests."""
from __future__ import annotations

from typing import Any

import pytest

from graph_dto import graph_fingerprint, validate_graph_v1
from metrics import calculate_graph_metrics

_SIZES = {"medium": 20, "large": 50}


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


def _build_graph(component_count: int) -> dict[str, Any]:
    graph: dict[str, Any] = {
        "schema_version": 1, "parser_semantics_version": 7,
        "project": {"fingerprint": ""}, "nodes": [], "edges": [],
        "callsites": [], "type_references": [], "import_references": [],
        "owner_structural_facts": [], "diagnostics": [],
    }
    nodes, edges = graph["nodes"], graph["edges"]
    module_id, module_path = "module:benchmark.service", "benchmark/service.py"
    nodes.append({"id": module_id, "kind": "module", "qualified_name": "benchmark.service",
                  "parent_id": None, "path": module_path, "location": _location(module_path, 1)})
    graph["owner_structural_facts"].append({
        "owner_id": module_id, "call_occurrences": 0,
        "direct_import_occurrences": {"project_local": 0, "non_project": 0},
    })
    components: list[dict[str, str]] = []
    for ordinal in range(1, component_count + 1):
        number = f"{ordinal:02d}"
        path = f"metrics_benchmark/component_{number}.py"
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
            {"id": ids["file"], "kind": "file", "qualified_name": f"metrics_benchmark.component_{number}",
             "parent_id": None, "path": path, "location": _location(path, 1)},
            {"id": ids["class"], "kind": "class", "class_kind": "class",
             "qualified_name": f"metrics_benchmark.component_{number}.Component{number}",
             "parent_id": ids["file"], "path": path, "location": _location(path, 10)},
            {"id": ids["field"], "kind": "field", "qualified_name": f"metrics_benchmark.component_{number}.Component{number}.value",
             "parent_id": ids["class"], "path": path, "location": _location(path, 12, 4)},
            {"id": ids["synthetic"], "kind": "method", "synthetic": True,
             "qualified_name": f"metrics_benchmark.component_{number}.Component{number}.__init__",
             "parent_id": ids["class"], "path": path, "location": _location(path, 10)},
            {"id": ids["method"], "kind": "method", "qualified_name": f"metrics_benchmark.component_{number}.Component{number}.run",
             "parent_id": ids["class"], "path": path, "location": _location(path, 20, 4),
             "complexity_facts": _complexity(path, 20, 4)},
            {"id": ids["function"], "kind": "function", "qualified_name": f"metrics_benchmark.component_{number}.build_{number}",
             "parent_id": ids["file"], "path": path, "location": _location(path, 40),
             "complexity_facts": _complexity(path, 40)},
            {"id": ids["constant"], "kind": "constant", "qualified_name": f"metrics_benchmark.component_{number}.LIMIT_{number}",
             "parent_id": ids["file"], "path": path, "location": _location(path, 5)},
        ])
        for child in (ids["class"], ids["function"], ids["constant"]):
            edges.append({"id": f"contains:{child}", "kind": "contains", "source_id": ids["file"], "target_id": child})
        for child in (ids["field"], ids["synthetic"], ids["method"]):
            edges.append({"id": f"contains:{child}", "kind": "contains", "source_id": ids["class"], "target_id": child})
        graph["owner_structural_facts"].extend([
            {"owner_id": ids["file"], "call_occurrences": 0,
             "direct_import_occurrences": {"project_local": 1, "non_project": 2}},
            {"owner_id": ids["method"], "call_occurrences": 5},
            {"owner_id": ids["function"], "call_occurrences": 0},
        ])

    for index, ids in enumerate(components):
        next_ids, prefix = components[(index + 1) % component_count], f"{index + 1:02d}"
        for offset, status in enumerate(("exact", "ambiguous", "external", "dynamic", "unresolved")):
            graph["callsites"].append({
                "id": f"call:{prefix}:{status}", "caller_id": ids["method"],
                "expression": f"invoke_{status}()", "location": _location(ids["path"], 21 + offset, 8),
                "syntactic_depth": 0, "resolution": status,
                "target_id": next_ids["method"] if status == "exact" else None,
                "candidate_ids": sorted([ids["function"], next_ids["method"]]) if status == "ambiguous" else [],
                "awaited": False,
            })
        edges.append({"id": f"calls:{prefix}", "kind": "calls", "source_id": ids["method"],
                      "target_id": next_ids["method"], "weight": 1})
        imports = (("exact", "from", "metrics_benchmark", f"component_{(index + 1) % component_count + 1:02d}", 0, next_ids["file"]),
                   ("external", "import", "", "requests", 0, None),
                   ("unresolved", "from", "missing", "adapter", 1, None))
        for offset, (status, kind, module, name, level, target) in enumerate(imports):
            identifier, location = f"import:{prefix}:{status}", _location(ids["path"], 2 + offset)
            graph["import_references"].append({
                "id": identifier, "importer_id": ids["file"], "kind": kind, "module": module,
                "name": name, "alias": None, "level": level, "location": location,
                "resolution": status, "target_id": target, "candidate_ids": [],
            })
            if status == "exact":
                edges.append({"id": f"imports:{identifier}", "kind": "imports",
                              "source_id": ids["file"], "target_id": target, "location": location})
        types = (("exact", ids["field"], "field_type", next_ids["class"], []),
                 ("ambiguous", ids["class"], "base", None, sorted([ids["class"], next_ids["class"]])),
                 ("external", ids["class"], "base", None, []),
                 ("unresolved", ids["class"], "base", None, []))
        for offset, (status, owner, role, target, candidates) in enumerate(types):
            graph["type_references"].append({
                "id": f"type:{prefix}:{status}", "owner_id": owner, "role": role,
                "expression": f"Type{offset}", "location": _location(ids["path"], 12 + offset, 8),
                "resolution": status, "target_id": target, "candidate_ids": candidates,
            })
        edges.extend([
            {"id": f"field_type:{prefix}", "kind": "field_type", "source_id": ids["field"], "target_id": next_ids["class"]},
            {"id": f"accesses_field:{prefix}", "kind": "accesses_field", "source_id": ids["method"],
             "target_id": ids["field"], "location": _location(ids["path"], 28, 8)},
        ])
        graph["diagnostics"].extend([
            {"id": f"diagnostic:{prefix}:import", "kind": "import_resolution", "status": "warning", "message": "Unresolved local import"},
            {"id": f"diagnostic:{prefix}:call", "kind": "call_resolution", "status": "info", "message": "Dynamic call"},
        ])
    graph["project"]["fingerprint"] = graph_fingerprint(graph)
    validate_graph_v1(graph)
    return graph


def build_representative_metrics_v2(size: str) -> dict[str, Any]:
    """Build a complete Metrics DTO with exact provenance for a fixed size."""
    if size not in _SIZES:
        raise ValueError(f"Unsupported representative metrics size {size!r}")
    graph = _build_graph(_SIZES[size])
    return {
        "schema_version": 1, "metrics_semantics_version": 4,
        "input": {"graph_schema_version": graph["schema_version"],
                  "graph_fingerprint": graph["project"]["fingerprint"]},
        "metrics": calculate_graph_metrics(graph),
    }


@pytest.mark.parametrize("size,count", _SIZES.items())
def test_fixture_exact_graph_composition_and_populations(size: str, count: int) -> None:
    graph = _build_graph(count)
    source = build_representative_metrics_v2(size)
    metrics = source["metrics"]
    kinds = [node["kind"] for node in graph["nodes"]]
    assert {kind: kinds.count(kind) for kind in ("file", "class", "field", "function", "constant")} == {
        "file": count, "class": count, "field": count, "function": count, "constant": count}
    assert kinds.count("method") == count * 2
    assert sum(node.get("synthetic") is True for node in graph["nodes"]) == count
    assert sum("complexity_facts" in node for node in graph["nodes"]) == count * 2
    assert metrics["size"]["classes"] == count
    assert metrics["size"]["functions"] == count
    assert metrics["size"]["methods"] == count
    assert metrics["code_quality"]["analyzed_callables"] == count * 2
    assert metrics["call_graph"]["nodes"] == count * 3
    assert metrics["dependency_graph"]["nodes"] == count + 1
    assert sum(edge["kind"] == "calls" for edge in graph["edges"]) == count


@pytest.mark.parametrize("size,count", _SIZES.items())
def test_fixture_exact_semantic_facts(size: str, count: int) -> None:
    graph = _build_graph(count)
    call_edges = [edge for edge in graph["edges"] if edge["kind"] == "calls"]
    assert len(graph["callsites"]) == count * 5
    assert {status: sum(row["resolution"] == status for row in graph["callsites"])
            for status in ("exact", "ambiguous", "external", "dynamic", "unresolved")} == dict.fromkeys(
                ("exact", "ambiguous", "external", "dynamic", "unresolved"), count)
    assert len(call_edges) == count
    assert all(
        edge["target_id"] == call_edges[(index + 1) % count]["source_id"]
        for index, edge in enumerate(call_edges)
    )
    assert {status: sum(row["resolution"] == status for row in graph["import_references"])
            for status in ("exact", "external", "unresolved")} == dict.fromkeys(
                ("exact", "external", "unresolved"), count)
    assert {status: sum(row["resolution"] == status for row in graph["type_references"])
            for status in ("exact", "ambiguous", "external", "unresolved")} == dict.fromkeys(
                ("exact", "ambiguous", "external", "unresolved"), count)
    assert sum(edge["kind"] == "field_type" for edge in graph["edges"]) == count
    assert sum(edge["kind"] == "accesses_field" for edge in graph["edges"]) == count
    assert len(graph["owner_structural_facts"]) == 1 + count * 3
    assert len(graph["diagnostics"]) == count * 2


def test_fixture_is_deterministic_fresh_and_has_valid_provenance() -> None:
    first, second = build_representative_metrics_v2("medium"), build_representative_metrics_v2("medium")
    assert first == second
    assert first is not second and first["metrics"] is not second["metrics"]
    first["metrics"]["size"]["files"] = -1
    assert second == build_representative_metrics_v2("medium")
    graph = _build_graph(_SIZES["medium"])
    validate_graph_v1(graph)
    assert graph["project"]["fingerprint"] == graph_fingerprint(graph)
    assert second["input"] == {"graph_schema_version": 1,
                               "graph_fingerprint": graph["project"]["fingerprint"]}
    assert second["schema_version"] == 1 and second["metrics_semantics_version"] == 4


def test_fixture_rejects_unsupported_size() -> None:
    with pytest.raises(ValueError, match="Unsupported representative metrics size"):
        build_representative_metrics_v2("small")


__all__ = ["build_representative_metrics_v2"]
