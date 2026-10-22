import json
import os
from copy import deepcopy
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch
from dataclasses import FrozenInstanceError

import pytest

from metrics import calculate_graph_metrics, calculate_metrics, load_graph
from graph_dto import graph_fingerprint, validate_graph_v1
from metrics.logic.projections import MetricsGraphProjection, iter_legacy_calls
from metrics.logic.serialization import (
    compact_graph_metrics,
    restore_graph_metrics,
    save_compact_graph_metrics,
    save_graph_metrics,
)


def _v3_metrics(graph: dict) -> dict:
    return calculate_graph_metrics(
        graph, canonical_mode=True, legacy_resolution=False,
        canonical_objects=True, canonical_calls=True,
    )


def _facts(path: str = "model.py", line: int = 1, *, controls: list[dict] | None = None) -> dict:
    location = {"path": path, "line": line, "column": 0}
    return {
        "span": {"start": location, "end": {**location, "column": 1}},
        "is_async": False,
        "controls": controls or [],
        "occurrences": [],
    }


def _canonical_call_graph() -> dict:
    """Small valid Graph DTO used to test metrics without invoking a producer."""
    def node(identifier: str, kind: str, qualified_name: str, path: str,
             *, parent_id: str | None = None) -> dict:
        location = {"path": path, "line": 1, "column": 0}
        item = {
            "id": identifier, "kind": kind, "qualified_name": qualified_name,
            "parent_id": parent_id, "path": path, "location": location,
        }
        if kind == "function":
            item["complexity_facts"] = _facts(path)
        return item

    graph = {
        "schema_version": 1,
        "parser_semantics_version": 7,
        "project": {"fingerprint": ""},
        "nodes": [
            node("file:provider.py", "file", "provider", "provider.py"),
            node("file:consumer.py", "file", "consumer", "consumer.py"),
            node("fn:available", "function", "provider.available", "provider.py", parent_id="file:provider.py"),
            node("fn:run", "function", "consumer.run", "consumer.py", parent_id="file:consumer.py"),
        ],
        "edges": [
            {"id": "contains:available", "kind": "contains", "source_id": "file:provider.py", "target_id": "fn:available"},
            {"id": "contains:run", "kind": "contains", "source_id": "file:consumer.py", "target_id": "fn:run"},
            {"id": "imports:local", "kind": "imports", "source_id": "file:consumer.py", "target_id": "file:provider.py", "location": {"path": "consumer.py", "line": 1, "column": 0}},
            {"id": "calls:run:available", "kind": "calls", "source_id": "fn:run", "target_id": "fn:available", "weight": 1},
        ],
        "callsites": [
            {"id": "call:exact", "caller_id": "fn:run", "expression": "available()", "location": {"path": "consumer.py", "line": 1, "column": 0}, "resolution": "exact", "target_id": "fn:available", "candidate_ids": [], "syntactic_depth": 0, "awaited": False},
            {"id": "call:external", "caller_id": "fn:run", "expression": "external()", "location": {"path": "consumer.py", "line": 2, "column": 0}, "resolution": "external", "target_id": None, "candidate_ids": [], "syntactic_depth": 0, "awaited": False},
            {"id": "call:unresolved", "caller_id": "fn:run", "expression": "unknown()", "location": {"path": "consumer.py", "line": 3, "column": 0}, "resolution": "unresolved", "target_id": None, "candidate_ids": [], "syntactic_depth": 0, "awaited": False},
        ],
        "import_references": [
            {"id": "local", "importer_id": "file:consumer.py", "kind": "import", "module": "", "name": "provider", "alias": None, "level": 0, "location": {"path": "consumer.py", "line": 1, "column": 0}, "resolution": "exact", "target_id": "file:provider.py", "candidate_ids": []},
            {"id": "external", "importer_id": "file:consumer.py", "kind": "import", "module": "", "name": "external", "alias": None, "level": 0, "location": {"path": "consumer.py", "line": 2, "column": 0}, "resolution": "external", "target_id": None, "candidate_ids": []},
        ],
        "owner_structural_facts": [
            {"owner_id": "file:provider.py", "call_occurrences": 0, "direct_import_occurrences": {"project_local": 0, "non_project": 0}},
            {"owner_id": "file:consumer.py", "call_occurrences": 0, "direct_import_occurrences": {"project_local": 1, "non_project": 1}},
            {"owner_id": "fn:available", "call_occurrences": 0},
            {"owner_id": "fn:run", "call_occurrences": 3},
        ],
        "type_references": [],
        "diagnostics": [],
    }
    graph["project"]["fingerprint"] = graph_fingerprint(graph)
    return graph


def test_semantics7_fixture_validates_and_is_accepted_by_public_file_api(tmp_path: Path) -> None:
    graph = _canonical_call_graph()
    validate_graph_v1(graph)
    graph_path = tmp_path / "graph.json"
    graph_path.write_text(json.dumps(graph), encoding="utf-8")

    result_path = calculate_metrics(graph_path, tmp_path / "metrics.json")
    result = json.loads(result_path.read_text(encoding="utf-8"))

    assert result["input"]["graph_fingerprint"] == graph["project"]["fingerprint"]
    assert result["metrics"]["call_graph"]["callsites_in_local_edges"] == 1


def test_metrics_projection_is_immutable_and_preserves_named_topologies() -> None:
    files = [
        {"name": "pkg", "path": "", "path_parts": [], "imports": []},
        {"name": "__init__", "path": "pkg", "path_parts": ["pkg"], "imports": []},
        {"name": "consumer", "path": "app", "path_parts": ["app"], "imports": [
            {"object": "pkg", "path": "pkg", "from_lib": False},
            {"object": "consumer", "path": "app.consumer", "from_lib": False},
            {"object": "unknown", "path": "unknown", "from_lib": False},
        ]},
    ]
    graph = {
        "body": [{"file": file} for file in files],
        "nodes": [
            {"id": "file", "kind": "file", "qualified_name": "app.consumer"},
            {"id": "fn", "kind": "function", "qualified_name": "app.consumer.run"},
        ],
        "edges": [
            {"kind": "calls", "source_id": "file", "target_id": "fn", "weight": 2},
            {"kind": "awaits", "source_id": "file", "target_id": "fn"},
        ],
        "callsites": [{"caller_id": "file", "resolution": "exact"}],
    }

    projection = MetricsGraphProjection.from_graph(graph)
    assert projection.effective_module_ids["pkg"] == "file:pkg/__init__.py"
    assert projection.directed_file_import_graph.edges == frozenset({
        ("app.consumer", "file:pkg/__init__.py")
    })
    assert projection.directed_package_import_graph.edges == frozenset({("app", "pkg")})
    assert projection.undirected_file_import_graph.edges == frozenset({
        ("app.consumer", "file:pkg/__init__.py")
    })
    assert projection.directed_canonical_call_graph.edge_weights[("file", "fn")] == 3
    with pytest.raises(TypeError):
        projection.nodes_by_id["other"] = {}  # type: ignore[index]
    with pytest.raises(TypeError):
        projection.directed_canonical_call_graph.edge_weights[("fn", "file")] = 1  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        projection.legacy_files[0].file_id = "changed"  # type: ignore[misc]


def test_metrics_projection_is_a_deeply_immutable_snapshot() -> None:
    graph = {
        "body": [{"file": {
            "name": "module", "path": "", "path_parts": [],
            "imports": [{"object": "dependency", "path": "dependency", "from_lib": False}],
        }}],
        "nodes": [{"id": "fn", "kind": "function", "metadata": {"tags": ["original"]}}],
        "edges": [],
        "callsites": [{"caller_id": "fn", "location": {"line": 1}}],
    }
    projection = MetricsGraphProjection.from_graph(graph)

    graph["body"][0]["file"]["imports"][0]["path"] = "changed"
    graph["nodes"][0]["metadata"]["tags"].append("changed")
    graph["callsites"][0]["location"]["line"] = 2

    assert projection.legacy_files[0].data["imports"][0]["path"] == "dependency"
    assert projection.nodes_by_id["fn"]["metadata"]["tags"] == ("original",)
    assert projection.callsites[0]["location"]["line"] == 1
    with pytest.raises(TypeError):
        projection.nodes_by_id["fn"]["metadata"]["tags"][0] = "changed"  # type: ignore[index]


def test_canonical_relation_projections_filter_deduplicate_and_snapshot() -> None:
    graph = {
        "nodes": [
            {"id": "c:A", "kind": "class"},
            {"id": "c:B", "kind": "class"},
            {"id": "f:x", "kind": "field"},
            {"id": "m:run", "kind": "method"},
            {"id": "fn:free", "kind": "function"},
        ],
        "edges": [
            {"kind": "inherits", "source_id": "c:A", "target_id": "c:B"},
            {"kind": "inherits", "source_id": "c:A", "target_id": "c:B"},
            {"kind": "inherits", "source_id": "c:A", "target_id": "c:A"},
            {"kind": "inherits", "source_id": "m:run", "target_id": "c:A"},
            {"kind": "inherits", "source_id": "c:A", "target_id": "missing"},
            {"kind": "field_type", "source_id": "f:x", "target_id": "c:B"},
            {"kind": "field_type", "source_id": "f:x", "target_id": "fn:free"},
            {"kind": "accesses_field", "source_id": "m:run", "target_id": "f:x"},
            {"kind": "accesses_field", "source_id": "fn:free", "target_id": "f:x"},
        ],
    }
    projection = MetricsGraphProjection.from_graph(graph)

    assert projection.directed_canonical_inheritance_graph.nodes == frozenset({
        "c:A", "c:B",
    })
    assert projection.directed_canonical_inheritance_graph.edges == frozenset({
        ("c:A", "c:B"), ("c:A", "c:A"),
    })
    assert projection.directed_canonical_field_type_graph.nodes == frozenset({
        "f:x", "c:A", "c:B",
    })
    assert projection.directed_canonical_field_type_graph.edges == frozenset({
        ("f:x", "c:B"),
    })
    assert projection.directed_canonical_field_access_graph.nodes == frozenset({
        "m:run", "f:x",
    })
    assert projection.directed_canonical_field_access_graph.edges == frozenset({
        ("m:run", "f:x"),
    })
    graph["edges"].clear()
    assert projection.directed_canonical_inheritance_graph.edges == frozenset({
        ("c:A", "c:B"), ("c:A", "c:A"),
    })
    with pytest.raises(FrozenInstanceError):
        projection.directed_canonical_inheritance_graph.edges = frozenset()  # type: ignore[misc]


def test_canonical_object_metrics_use_detached_relation_projections() -> None:
    from metrics.logic.object_metrics import calculate_canonical_object_metrics

    graph = _canonical_metrics_graph()
    projection = MetricsGraphProjection.from_graph(graph)
    wmc = {"c:A": 2, "c:B": 1, "c:C": 0}
    expected = calculate_canonical_object_metrics(
        graph, projection=projection, wmc_by_class_id=wmc,
    )
    graph["edges"].clear()

    assert calculate_canonical_object_metrics(
        graph, projection=projection, wmc_by_class_id=wmc,
    ) == expected


def test_semantics4_import_projection_uses_canonical_edges_not_legacy_body() -> None:
    graph = _canonical_call_graph()
    graph["parser_semantics_version"] = 4
    graph["body"] = [{"file": {"name": "consumer", "path": "", "path_parts": [], "imports": []}}]

    projection = MetricsGraphProjection.from_graph(graph)
    assert projection.directed_file_import_graph.edges == frozenset({
        ("file:consumer.py", "file:provider.py")
    })
    assert {item["resolution"] for item in projection.import_references} == {"exact", "external"}
    with pytest.raises(TypeError):
        projection.import_references[0]["resolution"] = "changed"  # type: ignore[index]


def test_semantics4_nested_imports_do_not_migrate_legacy_activity() -> None:
    graph = _canonical_call_graph()
    graph["parser_semantics_version"] = 4
    graph["body"] = [{"file": {"name": "consumer", "path": "", "path_parts": [], "imports": []}}]

    assert len(graph["import_references"]) == 2
    assert any(edge["kind"] == "imports" for edge in graph["edges"])
    consumer = next(item["file"] for item in graph["body"] if item["file"]["name"] == "consumer")
    assert consumer["imports"] == []
    assert calculate_graph_metrics(graph)["activity"]["local_imports"] == 0


def test_semantics4_package_projection_uses_first_path_segment_and_deduplicates() -> None:
    graph = {
        "parser_semantics_version": 4, "body": [], "callsites": [],
        "import_references": [{"id": "one"}, {"id": "two"}],
        "nodes": [
            {"id": "file:root.py", "kind": "file", "path": "root.py"},
            {"id": "file:pkg/a.py", "kind": "file", "path": "pkg/a.py"},
            {"id": "file:other/b.py", "kind": "file", "path": "other/b.py"},
        ],
        "edges": [
            {"kind": "imports", "source_id": "file:root.py", "target_id": "file:pkg/a.py"},
            {"kind": "imports", "source_id": "file:root.py", "target_id": "file:pkg/a.py"},
            {"kind": "imports", "source_id": "file:pkg/a.py", "target_id": "file:other/b.py"},
        ],
    }
    projection = MetricsGraphProjection.from_graph(graph)
    assert projection.directed_file_import_graph.edges == frozenset({
        ("file:root.py", "file:pkg/a.py"),
        ("file:pkg/a.py", "file:other/b.py"),
    })
    assert projection.directed_package_import_graph.nodes == frozenset({"<root>", "pkg", "other"})
    assert projection.directed_package_import_graph.edges == frozenset({
        ("<root>", "pkg"), ("pkg", "other"),
    })
    assert len(projection.import_references) == 2


def test_shared_legacy_call_traversal_keeps_order_depth_and_consumers_equal() -> None:
    calls = [{"object": "outer", "args": [
        {"value": {"type": "call", "object": "left", "args": [
            {"value": {"type": "call", "object": "deep", "args": []}}
        ]}},
        {"value": {"type": "name", "object": "ignored"}},
        {"value": {"type": "call", "object": "right", "args": []}},
    ]}, "not-a-call"]
    traversed = list(iter_legacy_calls(calls))
    assert [(item.call["object"], item.depth) for item in traversed] == [
        ("outer", 1), ("left", 2), ("deep", 3), ("right", 2)
    ]

    from metrics.logic.calculator import _calls_in
    from metrics.logic.object_metrics import _call_names

    assert _calls_in(calls) == 4
    assert _call_names(calls) == {"outer", "left", "deep", "right"}


def test_internal_metric_consumers_keep_projection_compatibility_fallback() -> None:
    from metrics.logic.call_graph import calculate_call_graph_metrics
    from metrics.logic.object_metrics import calculate_object_metrics
    from metrics.logic.quality import calculate_quality_metrics

    graph = _graph()
    projection = MetricsGraphProjection.from_graph(graph)
    assert calculate_call_graph_metrics(graph) == calculate_call_graph_metrics(
        graph, projection=projection
    )
    assert calculate_object_metrics(graph) == calculate_object_metrics(
        graph, projection=projection
    )
    assert calculate_quality_metrics(graph) == calculate_quality_metrics(
        graph, projection=projection
    )


def test_semantics3_complexity_consumers_use_facts_by_node_id() -> None:
    graph = _canonical_metrics_graph()
    graph["body"][0]["file"]["classes"][0]["methods"].append({
        "name": "legacy", "metrics": {"cyclomatic_complexity": 1}, "calls": [],
    })
    for node in graph["nodes"]:
        if node["kind"] in {"function", "method"}:
            node["complexity_facts"] = _facts()
            node.setdefault("location", {"path": "model.py", "line": 1, "column": 0})
    graph["parser_semantics_version"] = 3
    baseline = _v3_metrics(graph)

    body_mutation = deepcopy(graph)
    body_mutation["body"][0]["file"]["classes"][0]["methods"][0]["metrics"]["cyclomatic_complexity"] = 999
    changed_body = _v3_metrics(body_mutation)
    for section in ("code_quality", "object_oriented", "call_graph"):
        assert changed_body[section] == baseline[section]

    facts_mutation = deepcopy(graph)
    method = next(node for node in facts_mutation["nodes"] if node["kind"] == "method")
    method["complexity_facts"]["controls"].append({
        "kind": "boolean", "parent_index": None,
        "location": deepcopy(method["location"]),
        "operand_count": 4, "case_count": 0, "filter_count": 0,
    })
    changed_facts = _v3_metrics(facts_mutation)
    assert changed_facts["code_quality"] != baseline["code_quality"]
    assert changed_facts["object_oriented"] != baseline["object_oriented"]
    assert changed_facts["call_graph"]["risk_top"] != baseline["call_graph"]["risk_top"]

    permuted = deepcopy(graph)
    permuted["nodes"].reverse(); permuted["edges"].reverse(); permuted["callsites"].reverse()
    assert _v3_metrics(permuted) == baseline


def test_semantics3_synthetic_constructor_has_no_complexity_identity() -> None:
    graph = _canonical_call_graph()
    synthetic = {"id": "m:Empty.__init__", "kind": "method", "qualified_name": "model.Empty.__init__", "synthetic": True}
    graph["nodes"].append(synthetic)
    assert "complexity_facts" not in synthetic
    metrics = _v3_metrics(graph)
    assert metrics["code_quality"]["analyzed_callables"] == 2
    assert all(item["node"] != synthetic["qualified_name"] for item in metrics["call_graph"]["risk_top"])


def test_semantics3_synthetic_fan_in_does_not_normalize_real_callable_risk() -> None:
    def node(identifier: str, *, synthetic: bool = False) -> dict:
        item = {
            "id": identifier,
            "kind": "method" if synthetic else "function",
            "qualified_name": f"m.{identifier}",
            "complexity_facts": {
                "span": {
                    "start": {"path": "m.py", "line": 1, "column": 0},
                    "end": {"path": "m.py", "line": 1, "column": 1},
                },
                "is_async": False,
                "controls": [],
                "occurrences": [],
            },
        }
        if synthetic:
            item["synthetic"] = True
            item.pop("complexity_facts")
        return item

    graph = {
        "parser_semantics_version": 3,
        "nodes": [
            node("source_one"), node("source_two"), node("source_three"),
            node("real_target"), node("Synthetic.__init__", synthetic=True),
        ],
        "edges": [
            {"kind": "calls", "source_id": source, "target_id": "Synthetic.__init__"}
            for source in ("source_one", "source_two", "source_three")
        ] + [{"kind": "calls", "source_id": "source_one", "target_id": "real_target"}],
        "callsites": [],
    }

    call_graph = _v3_metrics(graph)["call_graph"]
    risks = {item["node"]: item for item in call_graph["risk_top"]}
    assert call_graph["highest_fan_in"] == {
        "degree": 3, "nodes": ["m.Synthetic.__init__"],
    }
    assert risks["m.real_target"]["score"] == 25.0


def test_frozen_legacy_graph_has_exact_metrics_contract() -> None:
    metrics = calculate_graph_metrics(_graph())
    assert metrics["size"] == {
        "files": 2, "directories": 1, "classes": 0, "functions": 1,
        "methods": 0, "fields": 0, "constants": 0,
        "abstract_classes": 0, "dataclasses": 0,
    }
    assert metrics["activity"]["calls"] == 2
    assert metrics["activity"]["average_calls_per_callable"] == 1.0
    assert metrics["dependency_graph"]["edges"] == 0
    assert metrics["call_graph"]["nodes"] == 2


def _graph() -> dict:
    return {
        "body": [
            {"file": {"name": "a", "path": "pkg", "path_parts": ["pkg"], "imports": [], "functions": [{"name": "f", "args": [], "return_type": None, "metrics": {"cyclomatic_complexity": 1}, "calls": [{"object": "g", "args": []}]}]}},
            {"file": {"name": "b", "path": "pkg", "path_parts": ["pkg"], "imports": [], "calls": [{"object": "print", "args": []}]}},
        ]
    }


def _v1(body: list[dict]) -> dict:
    graph = {
        "schema_version": 1, "parser_semantics_version": 1,
        "project": {"fingerprint": ""}, "nodes": [], "edges": [],
        "callsites": [], "diagnostics": [], "body": body,
    }
    graph["project"]["fingerprint"] = graph_fingerprint(graph)
    return graph


def _canonical_metrics_graph() -> dict:
    nodes = [
        {"id": "c:A", "kind": "class", "qualified_name": "m.A"},
        {"id": "c:B", "kind": "class", "qualified_name": "m.B"},
        {"id": "c:C", "kind": "class", "qualified_name": "m.C"},
        {"id": "f:A.x", "kind": "field", "qualified_name": "m.A.x", "parent_id": "c:A"},
        {"id": "m:A.one", "kind": "method", "qualified_name": "m.A.one", "parent_id": "c:A"},
        {"id": "m:A.two", "kind": "method", "qualified_name": "m.A.two", "parent_id": "c:A"},
        {"id": "m:B.work", "kind": "method", "qualified_name": "m.B.work", "parent_id": "c:B"},
        {"id": "fn:free", "kind": "function", "qualified_name": "m.free", "parent_id": "file:m.py"},
    ]
    edges = [
        {"kind": "inherits", "source_id": "c:B", "target_id": "c:A"},
        {"kind": "inherits", "source_id": "c:C", "target_id": "c:B"},
        {"kind": "field_type", "source_id": "f:A.x", "target_id": "c:B"},
        {"kind": "accesses_field", "source_id": "m:A.one", "target_id": "f:A.x"},
        {"kind": "accesses_field", "source_id": "m:A.two", "target_id": "f:A.x"},
        {"kind": "calls", "source_id": "m:A.one", "target_id": "m:B.work", "weight": 2},
        {"kind": "calls", "source_id": "m:A.one", "target_id": "m:A.one", "weight": 1},
        {"kind": "awaits", "source_id": "m:A.two", "target_id": "fn:free", "weight": 1},
    ]
    callsites = [
        {"caller_id": "m:A.one", "resolution": "exact", "target_id": "m:B.work", "syntactic_depth": 0},
        {"caller_id": "m:A.one", "resolution": "exact", "target_id": "m:B.work", "syntactic_depth": 1},
        {"caller_id": "m:A.one", "resolution": "exact", "target_id": "m:A.one", "syntactic_depth": 0},
        {"caller_id": "m:A.two", "resolution": "exact", "target_id": "fn:free", "syntactic_depth": 0},
        {"caller_id": "m:A.two", "resolution": "external", "syntactic_depth": 0},
        {"caller_id": "m:A.two", "resolution": "ambiguous", "syntactic_depth": 0},
        {"caller_id": "m:A.two", "resolution": "unresolved", "syntactic_depth": 0},
    ]
    body = [{"file": {"name": "m", "path": "", "path_parts": [], "imports": [], "classes": [
        {"name": name, "type": "class", "parent": "WRONG", "fields": [], "methods": []}
        for name in ("A", "B", "C")
    ]}}]
    return {"nodes": nodes, "edges": edges, "callsites": callsites, "body": body}


def test_canonical_v3_object_and_call_metrics_use_only_id_topology() -> None:
    graph = _canonical_metrics_graph()
    metrics = calculate_graph_metrics(graph, canonical_objects=True, canonical_calls=True)
    rows = {row["class"]: row for row in metrics["object_oriented"]["classes"]}
    assert (rows["m.A"]["dit"], rows["m.B"]["dit"], rows["m.C"]["dit"]) == (0, 1, 2)
    assert (rows["m.A"]["noc"], rows["m.B"]["noc"]) == (1, 1)
    assert (rows["m.A"]["cbo"], rows["m.A"]["rfc"], rows["m.A"]["lcom"]) == (1, 4, 0.0)
    call_graph = metrics["call_graph"]
    assert call_graph["nodes"] == 4
    assert call_graph["edges"] == 3
    assert call_graph["callsites_in_local_edges"] == 4
    assert call_graph["external_or_builtin_callsites"] == 1
    assert call_graph["unresolved_callsites"] == 2
    assert call_graph["maximum_syntactic_call_nesting"] == 2


def test_semantics2_canonical_objects_keep_frozen_body_derived_wmc() -> None:
    graph = _canonical_metrics_graph()
    graph["parser_semantics_version"] = 2
    graph["nodes"][0]["path"] = "m.py"
    graph["body"][0]["file"]["classes"][0]["methods"] = [
        {"name": "one", "metrics": {"cyclomatic_complexity": 4}},
        {"name": "two"},
    ]

    rows = {
        row["class"]: row
        for row in calculate_graph_metrics(
            graph, canonical_objects=True,
        )["object_oriented"]["classes"]
    }

    assert rows["m.A"]["wmc"] == 5
    assert rows["m.B"]["wmc"] == 0


def test_semantics2_wmc_matches_colliding_modules_by_source_path() -> None:
    graph = {
        "parser_semantics_version": 2,
        "body": [
            {"file": {"name": "pkg", "path": "", "path_parts": [], "classes": [
                {"name": "C", "methods": [
                    {"name": "root", "metrics": {"cyclomatic_complexity": 2}},
                ]},
            ]}},
            {"file": {"name": "__init__", "path": "pkg", "path_parts": ["pkg"], "classes": [
                {"name": "C", "methods": [
                    {"name": "package", "metrics": {"cyclomatic_complexity": 7}},
                ]},
            ]}},
        ],
        "nodes": [
            {"id": "class:pkg.py:C", "kind": "class", "qualified_name": "pkg.C", "path": "pkg.py"},
            {"id": "class:pkg/__init__.py:C", "kind": "class", "qualified_name": "pkg.C", "path": "pkg/__init__.py"},
        ],
        "edges": [], "callsites": [],
    }

    rows = calculate_graph_metrics(graph, canonical_objects=True)["object_oriented"]["classes"]
    assert {row["class"]: row["wmc"] for row in rows} == {
        "pkg.C [class:pkg.py:C]": 2,
        "pkg.C [class:pkg/__init__.py:C]": 7,
    }


def test_semantics2_wmc_preserves_defaults_empty_classes_and_occurrence_order() -> None:
    graph = {
        "parser_semantics_version": 2,
        "body": [{"file": {
            "name": "m", "path": "", "path_parts": [],
            "classes": [
                {"name": "Repeated", "methods": [{"name": "first"}]},
                {"name": "Repeated", "methods": [
                    {"name": "second", "metrics": {"cyclomatic_complexity": 6}},
                ]},
                {"name": "Empty", "methods": []},
            ],
        }}],
        "nodes": [
            {"id": "class:m.py:1:Repeated", "kind": "class", "qualified_name": "m.Repeated", "path": "m.py"},
            {"id": "method:synthetic", "kind": "method", "qualified_name": "m.Repeated.__init__",
             "parent_id": "class:m.py:1:Repeated", "path": "m.py", "synthetic": True},
            {"id": "class:m.py:2:Repeated", "kind": "class", "qualified_name": "m.Repeated", "path": "m.py"},
            {"id": "class:m.py:3:Empty", "kind": "class", "qualified_name": "m.Empty", "path": "m.py"},
        ],
        "edges": [], "callsites": [],
    }

    rows = {
        row["class"]: row
        for row in calculate_graph_metrics(
            graph, canonical_objects=True,
        )["object_oriented"]["classes"]
    }
    assert rows["m.Repeated [class:m.py:1:Repeated]"]["wmc"] == 1
    assert rows["m.Repeated [class:m.py:2:Repeated]"]["wmc"] == 6
    assert rows["m.Empty"]["wmc"] == 0
    assert rows["m.Repeated [class:m.py:1:Repeated]"]["rfc"] == 0


def test_semantics2_duplicate_wmc_is_independent_of_canonical_node_order() -> None:
    graph = {
        "parser_semantics_version": 2,
        "body": [{"file": {
            "name": "m", "path": "", "path_parts": [],
            "classes": [
                {"name": "Repeated", "methods": [
                    {"name": "first", "metrics": {"cyclomatic_complexity": 2}},
                ]},
                {"name": "Repeated", "methods": [
                    {"name": "second", "metrics": {"cyclomatic_complexity": 7}},
                ]},
            ],
        }}],
        "nodes": [
            {"id": "class:z:first", "kind": "class", "qualified_name": "m.Repeated",
             "path": "m.py", "location": {"path": "m.py", "line": 10, "column": 4}},
            {"id": "class:a:second", "kind": "class", "qualified_name": "m.Repeated",
             "path": "m.py", "location": {"path": "m.py", "line": 20, "column": 0}},
        ],
        "edges": [], "callsites": [],
    }

    baseline = calculate_graph_metrics(graph, canonical_objects=True)["object_oriented"]
    assert {
        row["class"]: row["wmc"] for row in baseline["classes"]
    } == {
        "m.Repeated [class:z:first]": 2,
        "m.Repeated [class:a:second]": 7,
    }
    for nodes in (list(reversed(graph["nodes"])), [graph["nodes"][1], graph["nodes"][0]]):
        permuted = deepcopy(graph)
        permuted["nodes"] = nodes
        assert calculate_graph_metrics(
            permuted, canonical_objects=True,
        )["object_oriented"] == baseline


def test_semantics7_canonical_wmc_does_not_depend_on_legacy_body() -> None:
    graph = _canonical_metrics_graph()
    graph["parser_semantics_version"] = 7
    graph["owner_structural_facts"] = []
    for node in graph["nodes"]:
        if node["kind"] in {"function", "method"}:
            node["complexity_facts"] = _facts()
            graph["owner_structural_facts"].append({
                "owner_id": node["id"], "call_occurrences": 0,
            })
    baseline = calculate_graph_metrics(graph, canonical_objects=True)["object_oriented"]

    changed = deepcopy(graph)
    changed["body"][0]["file"]["classes"][0]["methods"] = [
        {"name": "legacy", "metrics": {"cyclomatic_complexity": 999}},
    ]

    assert calculate_graph_metrics(
        changed, canonical_objects=True,
    )["object_oriented"] == baseline


def test_canonical_v3_module_calls_are_full_call_graph_owners() -> None:
    graph = _canonical_call_graph()
    call_graph = calculate_graph_metrics(graph, canonical_calls=True)["call_graph"]
    assert (call_graph["external_or_builtin_callsites"], call_graph["unresolved_callsites"]) == (1, 1)
    assert call_graph["callsites_in_local_edges"] == 1
    assert call_graph["local_resolution_rate"] == 0.3333
    assert call_graph["classified_callsite_rate"] == 0.6667
    assert call_graph["node_kinds"] == {"function": 2}
    assert call_graph["nodes"] == 2
    assert call_graph["edges"] == 1
    assert "consumer.run" in call_graph["entrypoints"]
    assert call_graph["longest_call_chain"] == ["consumer.run", "provider.available"]
    assert call_graph["heaviest_edges"] == [{
        "caller": "consumer.run", "target": "provider.available", "callsites": 1,
    }]
    assert call_graph["maximum_syntactic_call_nesting"] == 1


def test_canonical_v3_cycles_and_legacy_name_mutations_do_not_change_topology() -> None:
    graph = _canonical_metrics_graph()
    graph["edges"].extend([
        {"kind": "inherits", "source_id": "c:A", "target_id": "c:C"},
        {"kind": "inherits", "source_id": "c:A", "target_id": "c:A"},
    ])
    first = calculate_graph_metrics(graph, canonical_objects=True, canonical_calls=True)
    changed = deepcopy(graph)
    changed["body"][0]["file"]["classes"][0].update({"parent": "OTHER", "fields": [{"name": "renamed", "type": "Nope"}]})
    second = calculate_graph_metrics(changed, canonical_objects=True, canonical_calls=True)
    assert first["object_oriented"] == second["object_oriented"]
    assert first["call_graph"] == second["call_graph"]
    assert all(row["dit"] is None for row in first["object_oriented"]["classes"])


def test_canonical_v3_object_invariants_and_permutation_are_exact() -> None:
    graph = _canonical_metrics_graph()
    graph["nodes"].extend([
        {"id": "c:D", "kind": "class", "qualified_name": "m.D"},
        {"id": "f:A.y", "kind": "field", "qualified_name": "m.A.y", "parent_id": "c:A"},
        {"id": "m:A.three", "kind": "method", "qualified_name": "m.A.three", "parent_id": "c:A"},
    ])
    graph["edges"].extend([
        {"kind": "inherits", "source_id": "c:D", "target_id": "c:C"},
        {"kind": "accesses_field", "source_id": "m:A.three", "target_id": "f:A.y"},
    ])

    first = calculate_graph_metrics(
        graph, canonical_objects=True, canonical_calls=True
    )
    permuted = deepcopy(graph)
    permuted["nodes"].reverse()
    permuted["edges"].reverse()
    permuted["callsites"].reverse()
    second = calculate_graph_metrics(
        permuted, canonical_objects=True, canonical_calls=True
    )

    assert first["object_oriented"] == second["object_oriented"]
    assert first["call_graph"] == second["call_graph"]
    rows = {row["class"]: row for row in first["object_oriented"]["classes"]}
    assert (rows["m.A"]["dit"], rows["m.B"]["dit"], rows["m.C"]["dit"], rows["m.D"]["dit"]) == (0, 1, 2, 3)
    assert (rows["m.A"]["noc"], rows["m.B"]["noc"], rows["m.C"]["noc"], rows["m.D"]["noc"]) == (1, 1, 1, 0)
    assert (rows["m.A"]["cbo"], rows["m.A"]["rfc"], rows["m.A"]["lcom"]) == (1, 5, 0.6667)
    assert all(
        row["lcom"] is None or 0.0 <= row["lcom"] <= 1.0
        for row in rows.values()
    )


def test_canonical_v3_reachable_cycle_marks_descendant_dit_unknown() -> None:
    graph = _canonical_metrics_graph()
    graph["nodes"].append(
        {"id": "c:D", "kind": "class", "qualified_name": "m.D"}
    )
    graph["edges"].extend([
        {"kind": "inherits", "source_id": "c:A", "target_id": "c:C"},
        {"kind": "inherits", "source_id": "c:D", "target_id": "c:C"},
    ])
    rows = {
        row["class"]: row
        for row in calculate_graph_metrics(
            graph, canonical_objects=True, canonical_calls=True
        )["object_oriented"]["classes"]
    }
    assert all(rows[name]["dit"] is None for name in ("m.A", "m.B", "m.C", "m.D"))
    assert (rows["m.A"]["noc"], rows["m.B"]["noc"], rows["m.C"]["noc"]) == (1, 1, 2)


def test_full_metrics_and_file_api_are_deterministic(tmp_path: Path) -> None:
    graph_path = tmp_path / "graph.json"
    graph_path.write_text(json.dumps(_graph()), encoding="utf-8")
    first = calculate_metrics(graph_path, tmp_path / "first.json")
    second = calculate_metrics(graph_path, tmp_path / "second.json")
    result = json.loads(first.read_text(encoding="utf-8"))

    assert first.read_bytes() == second.read_bytes()
    assert result["input"]["graph_fingerprint"]
    assert set(result["input"]) == {"graph_schema_version", "graph_fingerprint"}
    assert result["input"]["graph_schema_version"] is None
    assert set(result["metrics"]) == {"size", "activity", "dependency_graph", "architecture", "code_quality", "object_oriented", "call_graph"}
    assert result["metrics"]["activity"]["average_calls_per_call_owner"] == 1.0


@pytest.mark.parametrize("fixture_name", [".", "package_calls"])
def test_calculate_metrics_matches_complete_committed_golden(
    tmp_path: Path, fixture_name: str,
) -> None:
    fixtures = (
        Path(__file__).resolve().parents[1]
        / "gpt_work_dir/tests/golden_v1"
        / fixture_name
    )
    result_path = calculate_metrics(fixtures / "graph.json", tmp_path / "metrics.json")

    actual = json.loads(result_path.read_text(encoding="utf-8"))
    expected = json.loads((fixtures / "metrics.json").read_text(encoding="utf-8"))
    assert actual == expected


def test_calculate_metrics_keeps_canonical_json_bytes(tmp_path: Path) -> None:
    graph_path = tmp_path / "graph.json"
    graph_path.write_text(json.dumps(_graph()), encoding="utf-8")

    result_path = calculate_metrics(graph_path, tmp_path / "nested" / "metrics.json")
    envelope = json.loads(result_path.read_text(encoding="utf-8"))

    assert result_path == result_path.resolve()
    assert result_path.read_bytes() == (
        json.dumps(envelope, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def test_compatibility_json_writers_preserve_formats_and_restore(tmp_path: Path) -> None:
    metrics = {
        "zeta": "Привет",
        "rows": [{"name": "один", "value": 1}, {"name": "два", "value": 2}],
    }

    full_path = save_graph_metrics(metrics, tmp_path / "full" / "metrics.json")
    compact_path = save_compact_graph_metrics(metrics, tmp_path / "compact.json")

    assert full_path == full_path.resolve()
    assert compact_path == compact_path.resolve()
    assert full_path.read_bytes() == (
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    assert compact_path.read_bytes() == (
        json.dumps(
            compact_graph_metrics(metrics),
            ensure_ascii=False,
            separators=(",", ":"),
        ) + "\n"
    ).encode("utf-8")
    assert restore_graph_metrics(json.loads(compact_path.read_text(encoding="utf-8"))) == metrics
    assert not list(tmp_path.glob(".metrics.json.*"))


def test_average_calls_per_call_owner_keeps_legacy_hybrid_denominator() -> None:
    """All callables count, while only modules that call are module owners."""
    function = lambda name, calls=[]: {
        "name": name,
        "metrics": {"cyclomatic_complexity": 1},
        "calls": calls,
    }
    graph = {
        "body": [{
            "file": {
                "name": "owners",
                "path": "",
                "path_parts": [],
                "imports": [],
                "functions": [
                    function("active", [{"object": "target", "args": []}]),
                    function("idle_one"),
                    function("idle_two"),
                ],
                "calls": [
                    {"object": "first", "args": []},
                    {"object": "second", "args": []},
                ],
            }
        }]
    }

    activity = calculate_graph_metrics(graph)["activity"]

    # Legacy semantics v1/v2: 3 calls / (3 callables + 1 active module).
    assert activity["average_calls_per_call_owner"] == 0.75
    # An active-owner formula would divide by active + module == 2 instead.
    assert activity["average_calls_per_call_owner"] != 1.5


def test_metrics_fingerprint_ignores_root_body_order(tmp_path: Path) -> None:
    graph = _graph()
    equivalent = deepcopy(graph)
    equivalent["body"].reverse()
    compact = tmp_path / "compact.json"
    formatted = tmp_path / "formatted.json"
    compact.write_text(json.dumps(graph, separators=(",", ":")), encoding="utf-8")
    formatted.write_text(json.dumps(equivalent, indent=4, sort_keys=True), encoding="utf-8")

    first = json.loads(calculate_metrics(compact, tmp_path / "first.json").read_text(encoding="utf-8"))
    second = json.loads(calculate_metrics(formatted, tmp_path / "second.json").read_text(encoding="utf-8"))

    assert first == second


def test_metrics_fingerprint_preserves_nested_list_order(tmp_path: Path) -> None:
    graph = _graph()
    graph["body"][0]["file"]["functions"][0]["calls"].append(
        {"object": "h", "args": []}
    )
    reordered = deepcopy(graph)
    reordered["body"][0]["file"]["functions"][0]["calls"].reverse()

    first_path = tmp_path / "first-graph.json"
    second_path = tmp_path / "second-graph.json"
    first_path.write_text(json.dumps(graph), encoding="utf-8")
    second_path.write_text(json.dumps(reordered), encoding="utf-8")

    first = json.loads(calculate_metrics(first_path, tmp_path / "first.json").read_text(encoding="utf-8"))
    second = json.loads(calculate_metrics(second_path, tmp_path / "second.json").read_text(encoding="utf-8"))

    assert first["input"]["graph_fingerprint"] != second["input"]["graph_fingerprint"]


def test_metrics_fingerprint_preserves_nested_body_key_order(tmp_path: Path) -> None:
    graph = _graph()
    graph["body"][0]["file"]["metadata"] = {"body": [{"name": "first"}, {"name": "second"}]}
    reordered = deepcopy(graph)
    reordered["body"][0]["file"]["metadata"]["body"].reverse()

    first_path = tmp_path / "first-graph.json"
    second_path = tmp_path / "second-graph.json"
    first_path.write_text(json.dumps(graph), encoding="utf-8")
    second_path.write_text(json.dumps(reordered), encoding="utf-8")

    first = json.loads(calculate_metrics(first_path, tmp_path / "first.json").read_text(encoding="utf-8"))
    second = json.loads(calculate_metrics(second_path, tmp_path / "second.json").read_text(encoding="utf-8"))

    assert first["input"]["graph_fingerprint"] != second["input"]["graph_fingerprint"]


def test_longest_call_chain_uses_lexical_tie_break(tmp_path: Path) -> None:
    functions = [
        {"name": "root", "args": [], "return_type": None, "metrics": {"cyclomatic_complexity": 1}, "calls": [{"object": "right", "args": []}, {"object": "left", "args": []}]},
        {"name": "right", "args": [], "return_type": None, "metrics": {"cyclomatic_complexity": 1}, "calls": [{"object": "right_leaf", "args": []}]},
        {"name": "left", "args": [], "return_type": None, "metrics": {"cyclomatic_complexity": 1}, "calls": [{"object": "left_leaf", "args": []}]},
        {"name": "right_leaf", "args": [], "return_type": None, "metrics": {"cyclomatic_complexity": 1}, "calls": []},
        {"name": "left_leaf", "args": [], "return_type": None, "metrics": {"cyclomatic_complexity": 1}, "calls": []},
    ]
    graph = {"body": [{"file": {"name": "paths", "path": "pkg", "path_parts": ["pkg"], "imports": [], "functions": functions}}]}
    path = tmp_path / "graph.json"
    path.write_text(json.dumps(graph), encoding="utf-8")

    result = json.loads(calculate_metrics(path, tmp_path / "metrics.json").read_text(encoding="utf-8"))

    assert result["metrics"]["call_graph"]["longest_call_chain"] == [
        "pkg.paths.root", "pkg.paths.left", "pkg.paths.left_leaf"
    ]


def test_loader_rejects_bad_and_versioned_input(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("[", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid graph JSON"):
        load_graph(bad)
    bad.write_text('{"schema_version": 1, "body": []}', encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported"):
        load_graph(bad)


@pytest.mark.parametrize(
    ("mutate", "path"),
    [
        (lambda graph: graph["body"][0].pop("file"), "body[0].file"),
        (lambda graph: graph["body"][0]["file"].__setitem__("imports", {}), "body[0].file.imports"),
        (lambda graph: graph["body"][0]["file"].__setitem__("classes", [{"type": "class", "methods": {}, "fields": []}]), "body[0].file.classes[0].methods"),
        (lambda graph: graph["body"][0]["file"].__setitem__("functions", [{"metrics": {"cyclomatic_complexity": 1}, "calls": {}}]), "body[0].file.functions[0].calls"),
        (lambda graph: graph["body"][0]["file"].__setitem__("calls", [{"args": [None]}]), "body[0].file.calls[0].args[0]"),
        (lambda graph: graph["body"][0]["file"].__setitem__("calls", [{"args": [{"value": {"type": "call", "args": {}}}]}]), "body[0].file.calls[0].args[0].value[0].args"),
    ],
)
def test_loader_validates_legacy_containers_before_calculation(
    tmp_path: Path, mutate: Callable[[dict], None], path: str
) -> None:
    graph = _graph()
    mutate(graph)
    graph_path = tmp_path / "graph.json"
    graph_path.write_text(json.dumps(graph), encoding="utf-8")

    with pytest.raises(ValueError, match=path.replace("[", r"\[").replace("]", r"\]")):
        calculate_metrics(graph_path, tmp_path / "metrics.json")


@pytest.mark.parametrize(
    ("mutate", "path"),
    [
        (lambda graph: graph["body"][0].__setitem__("file", {}), "body[0].file.name"),
        (lambda graph: graph["body"][0]["file"].pop("name"), "body[0].file.name"),
        (lambda graph: graph["body"][0]["file"].__setitem__("name", 1), "body[0].file.name"),
        (lambda graph: graph["body"][0]["file"].pop("path"), "body[0].file.path"),
        (lambda graph: graph["body"][0]["file"].__setitem__("path", 1), "body[0].file.path"),
        (lambda graph: graph["body"][0]["file"].pop("path_parts"), "body[0].file.path_parts"),
        (lambda graph: graph["body"][0]["file"].__setitem__("path_parts", ["other"]), "body[0].file"),
        (lambda graph: graph["body"][0]["file"].__setitem__("path_parts", [1]), "body[0].file.path_parts"),
        (lambda graph: graph["body"][0]["file"].pop("imports"), "body[0].file.imports"),
        (lambda graph: graph["body"][0]["file"].__setitem__("imports", [None]), "body[0].file.imports[0]"),
        (lambda graph: graph["body"][0]["file"].__setitem__("imports", [{"from_lib": True}]), "body[0].file.imports[0]"),
        (lambda graph: graph["body"][0]["file"].__setitem__("imports", [{"object": "x", "from_lib": 1}]), "body[0].file.imports[0]"),
        (lambda graph: graph["body"].append({"file": dict(graph["body"][0]["file"])}), "Duplicate file"),
        (lambda graph: graph["body"][0]["file"].__setitem__("classes", [{"type": "invalid", "methods": []}]), "body[0].file.classes[0].type"),
        (lambda graph: graph["body"][0]["file"].__setitem__("classes", [{}]), "body[0].file.classes[0].type"),
        (lambda graph: graph["body"][0]["file"]["functions"][0].pop("metrics"), "body[0].file.functions[0].metrics"),
        (lambda graph: graph["body"][0]["file"]["functions"][0].__setitem__("metrics", []), "body[0].file.functions[0].metrics"),
        (lambda graph: graph["body"][0]["file"]["functions"][0].__setitem__("metrics", {"cyclomatic_complexity": 0}), "body[0].file.functions[0].metrics"),
    ],
)
def test_loader_enforces_parser_legacy_graph_invariants(
    tmp_path: Path, mutate: Callable[[dict], None], path: str
) -> None:
    graph = _graph()
    mutate(graph)
    graph_path = tmp_path / "graph.json"
    graph_path.write_text(json.dumps(graph), encoding="utf-8")

    with pytest.raises(ValueError, match=path.replace("[", r"\[").replace("]", r"\]")):
        load_graph(graph_path)


def test_calculate_metrics_cleans_up_when_replace_fails(tmp_path: Path) -> None:
    graph_path = tmp_path / "graph.json"
    graph_path.write_text(json.dumps(_graph()), encoding="utf-8")
    target = tmp_path / "metrics.json"
    target.write_text("old metrics", encoding="utf-8")

    with patch("metrics.logic.serialization.os.replace", side_effect=OSError("injected failure")):
        with pytest.raises(OSError, match="injected failure"):
            calculate_metrics(graph_path, target)

    assert target.read_text(encoding="utf-8") == "old metrics"
    assert not list(tmp_path.glob(".metrics.json.*"))


def test_compatibility_writer_cleans_up_on_serialization_failure(tmp_path: Path) -> None:
    target = tmp_path / "metrics.json"
    target.write_text("old metrics", encoding="utf-8")

    with pytest.raises(TypeError):
        save_graph_metrics({"invalid": object()}, target)

    assert target.read_text(encoding="utf-8") == "old metrics"
    assert not list(tmp_path.glob(".metrics.json.*"))


def test_compatibility_writer_cleans_up_on_keyboard_interrupt(tmp_path: Path) -> None:
    target = tmp_path / "metrics.json"
    target.write_text("old metrics", encoding="utf-8")

    interruption = KeyboardInterrupt()
    with patch(
        "metrics.logic.serialization.json.dump", side_effect=interruption
    ):
        with pytest.raises(KeyboardInterrupt) as caught:
            save_graph_metrics({"value": 1}, target)

    assert caught.value is interruption
    assert target.read_text(encoding="utf-8") == "old metrics"
    assert not list(tmp_path.glob(".metrics.json.*"))


def test_compatibility_writer_closes_descriptor_when_fdopen_fails(tmp_path: Path) -> None:
    from metrics.logic import serialization

    target = tmp_path / "metrics.json"
    target.write_text("old metrics", encoding="utf-8")
    original_mkstemp = serialization.tempfile.mkstemp
    descriptors: list[int] = []

    def capture_mkstemp(*args, **kwargs) -> tuple[int, str]:
        descriptor, temporary = original_mkstemp(*args, **kwargs)
        descriptors.append(descriptor)
        return descriptor, temporary

    failure = KeyboardInterrupt()
    with patch(
        "metrics.logic.serialization.tempfile.mkstemp", side_effect=capture_mkstemp
    ), patch("metrics.logic.serialization.os.fdopen", side_effect=failure):
        with pytest.raises(KeyboardInterrupt) as caught:
            save_graph_metrics({"value": 1}, target)

    assert caught.value is failure
    assert len(descriptors) == 1
    with pytest.raises(OSError):
        os.fstat(descriptors[0])
    assert target.read_text(encoding="utf-8") == "old metrics"
    assert not list(tmp_path.glob(".metrics.json.*"))


def test_cleanup_failure_does_not_mask_serialization_failure(tmp_path: Path) -> None:
    from metrics.logic import serialization

    target = tmp_path / "metrics.json"
    target.write_text("old metrics", encoding="utf-8")
    original_unlink = serialization.os.unlink
    unlink_calls = 0

    def fail_first_unlink(path: str | Path) -> None:
        nonlocal unlink_calls
        unlink_calls += 1
        if unlink_calls == 1:
            raise SystemExit("injected cleanup failure")
        original_unlink(path)

    failure = ValueError("injected serialization failure")
    try:
        with patch(
            "metrics.logic.serialization.json.dump", side_effect=failure
        ), patch("metrics.logic.serialization.os.unlink", side_effect=fail_first_unlink):
            with pytest.raises(ValueError) as caught:
                save_graph_metrics({"value": 1}, target)

        temporary_files = list(tmp_path.glob(".metrics.json.*"))
        assert caught.value is failure
        assert target.read_text(encoding="utf-8") == "old metrics"
        assert len(temporary_files) == 1
    finally:
        for temporary_file in tmp_path.glob(".metrics.json.*"):
            original_unlink(temporary_file)
    assert not list(tmp_path.glob(".metrics.json.*"))


def test_loader_accepts_frozen_legacy_graph(tmp_path: Path) -> None:
    fixture = tmp_path / "graph.json"
    fixture.write_text(json.dumps(_graph()), encoding="utf-8")
    assert load_graph(fixture) == _graph()


def test_nontrivial_legacy_graph_has_frozen_expected_metrics() -> None:
    current = calculate_graph_metrics(_graph())
    assert current["activity"]["calls"] == 2
    assert current["code_quality"]["analyzed_callables"] == 1
    assert current["call_graph"]["heaviest_edges"] == []
    assert current["call_graph"]["unresolved_callsites"] == 1


def test_graph_v1_metrics_use_canonical_fingerprint_and_report_cyclic_dit(tmp_path: Path) -> None:
    classes = [{"name": "A", "type": "class", "parent": "B", "methods": [], "fields": []},
               {"name": "B", "type": "class", "parent": "A", "methods": [], "fields": []},
               {"name": "Child", "type": "class", "parent": "A", "methods": [], "fields": []}]
    graph = _v1([{"file": {"name": "models", "path": "", "path_parts": [], "imports": [], "classes": classes}}])
    graph_path = tmp_path / "graph.json"
    graph_path.write_text(json.dumps(graph), encoding="utf-8")
    result = json.loads(calculate_metrics(graph_path, tmp_path / "metrics.json").read_text(encoding="utf-8"))

    assert result["metrics_semantics_version"] == 2
    assert result["input"]["graph_schema_version"] == 1
    assert result["input"]["graph_fingerprint"] == graph["project"]["fingerprint"]
    assert result["input"]["legacy_body_fingerprint"]
    rows = {row["class"]: row["dit"] for row in result["metrics"]["object_oriented"]["classes"]}
    assert rows == {"models.A": None, "models.B": None, "models.Child": None}
    assert result["metrics"]["object_oriented"]["deepest_inheritance"] == []

    graph["body"].reverse()
    reordered = tmp_path / "reordered.json"
    reordered.write_text(json.dumps(graph), encoding="utf-8")
    again = json.loads(calculate_metrics(reordered, tmp_path / "again.json").read_text(encoding="utf-8"))
    assert again["input"]["graph_fingerprint"] == result["input"]["graph_fingerprint"]
    assert again["input"]["legacy_body_fingerprint"] == result["input"]["legacy_body_fingerprint"]


def test_package_initializer_wins_module_collision_in_v1_metrics(tmp_path: Path) -> None:
    function = lambda name, calls=[]: {"name": name, "metrics": {"cyclomatic_complexity": 1}, "calls": calls}
    body = [
        {"file": {"name": "pkg", "path": "", "path_parts": [], "imports": [], "functions": [function("wrong")]}},
        {"file": {"name": "__init__", "path": "pkg", "path_parts": ["pkg"], "imports": [], "functions": [function("chosen")]}},
        {"file": {"name": "consumer", "path": "", "path_parts": [], "imports": [{"object": "chosen", "path": "pkg", "from_lib": False}], "functions": [function("run", [{"object": "chosen", "semantic_target": {"module": "pkg", "object": "chosen"}, "args": []}])]}},
    ]
    graph_path = tmp_path / "graph.json"
    graph_path.write_text(json.dumps(_v1(body)), encoding="utf-8")

    result = json.loads(calculate_metrics(graph_path, tmp_path / "metrics.json").read_text(encoding="utf-8"))
    dependencies = result["metrics"]["dependency_graph"]
    assert dependencies["edges"] == 1
    assert dependencies["nodes"] == 3
    assert dependencies["highest_fan_in"] == {"degree": 1, "files": ["file:pkg/__init__.py"]}
    assert dependencies["highest_fan_out"] == {"degree": 1, "files": ["consumer"]}
    assert dependencies["isolated_files"] == ["file:pkg.py"]
    assert result["metrics"]["call_graph"]["heaviest_edges"][0]["target"] == "file:pkg/__init__.py.chosen"


def test_module_prefix_resolves_to_effective_file_during_collision(tmp_path: Path) -> None:
    function = lambda name, calls=[]: {"name": name, "metrics": {"cyclomatic_complexity": 1}, "calls": calls}
    body = [
        {"file": {"name": "pkg", "path": "", "path_parts": [], "imports": [], "functions": [function("wrong")]}},
        {"file": {"name": "__init__", "path": "pkg", "path_parts": ["pkg"], "imports": [], "functions": [function("chosen")]}},
        {"file": {"name": "consumer", "path": "", "path_parts": [], "imports": [{"object": "pkg", "path": "pkg", "from_lib": False}], "functions": [function("run", [{"object": "pkg.chosen", "semantic_target": {"module": "pkg", "object": "chosen"}, "args": []}])]}},
    ]
    graph_path = tmp_path / "graph.json"
    graph_path.write_text(json.dumps(_v1(body)), encoding="utf-8")

    result = json.loads(calculate_metrics(graph_path, tmp_path / "metrics.json").read_text(encoding="utf-8"))
    assert result["metrics"]["call_graph"]["heaviest_edges"][0] == {
        "caller": "consumer.run",
        "target": "file:pkg/__init__.py.chosen",
        "callsites": 1,
    }


def test_v1_body_change_has_separate_metric_input_identity(tmp_path: Path) -> None:
    first = _v1(_graph()["body"])
    changed = deepcopy(first)
    changed["body"][0]["file"]["functions"][0]["calls"].append({"object": "h", "args": []})
    paths = []
    for index, graph in enumerate((first, changed)):
        path = tmp_path / f"graph-{index}.json"; path.write_text(json.dumps(graph), encoding="utf-8")
        paths.append(json.loads(calculate_metrics(path, tmp_path / f"metrics-{index}.json").read_text(encoding="utf-8")))
    assert paths[0]["input"]["graph_fingerprint"] == paths[1]["input"]["graph_fingerprint"]
    assert paths[0]["input"]["legacy_body_fingerprint"] != paths[1]["input"]["legacy_body_fingerprint"]


def test_scc_rows_are_deterministic_when_legacy_body_order_changes() -> None:
    files = [
        {"name": name, "path": "", "path_parts": [], "imports": [{"object": target, "path": target, "from_lib": False}]}
        for name, target in (("a", "b"), ("b", "a"), ("c", "d"), ("d", "c"))
    ]
    graph = {"body": [{"file": file} for file in files]}
    reversed_graph = {"body": list(reversed(graph["body"]))}

    first = calculate_graph_metrics(graph)["dependency_graph"]["cyclic_components"]
    second = calculate_graph_metrics(reversed_graph)["dependency_graph"]["cyclic_components"]
    assert first == second == [["a", "b"], ["c", "d"]]


def test_scc_and_canonical_dit_handle_chains_beyond_recursion_limit() -> None:
    from metrics.logic.calculator import _strong_components
    from metrics.logic.call_graph import _strong_components as call_scc

    count = 1200
    nodes = {str(index) for index in range(count)}
    edges = {(str(index), str(index + 1)) for index in range(count - 1)}
    assert len(_strong_components(nodes, edges)) == count
    assert len(call_scc(nodes, edges)) == count

    dag_nodes = {"0", "1", "2"}
    dag_edges = {("0", "1"), ("0", "2"), ("1", "2")}
    expected = [{"0"}, {"1"}, {"2"}]
    assert _strong_components(dag_nodes, dag_edges) == expected
    assert call_scc(dag_nodes, dag_edges) == expected

    classes = []
    for index in range(count):
        item = {"name": f"C{index}", "type": "class", "methods": [], "fields": []}
        if index: item["parent"] = f"C{index - 1}"
        classes.append(item)
    graph = {"body": [{"file": {"name": "chain", "path": "", "path_parts": [], "imports": [], "classes": classes}}]}
    rows = calculate_graph_metrics(graph, canonical_mode=True)["object_oriented"]["classes"]
    assert {row["class"]: row["dit"] for row in rows}[f"chain.C{count - 1}"] == count - 1


def test_architecture_graph_algorithms_handle_deep_package_graphs() -> None:
    from metrics.logic.architecture import _critical_topology, _cyclic_components

    count = 1200
    nodes = {str(index) for index in range(count)}
    chain = {(str(index), str(index + 1)) for index in range(count - 1)}
    articulation, bridges = _critical_topology(nodes, chain)
    assert len(articulation) == count - 2
    assert len(bridges) == count - 1
    assert _cyclic_components(nodes, chain) == []

    cycle = chain | {(str(count - 1), "0")}
    assert _cyclic_components(nodes, cycle) == [sorted(nodes)]


def test_dotted_external_parent_does_not_bind_to_local_short_name() -> None:
    classes = [{"name": "Base", "type": "class", "methods": [], "fields": []},
               {"name": "Child", "type": "class", "parent": "ext.Base", "methods": [], "fields": []}]
    graph = {"body": [{"file": {"name": "models", "path": "", "path_parts": [], "imports": [], "classes": classes}}]}
    rows = {row["class"]: row for row in calculate_graph_metrics(graph, canonical_mode=True)["object_oriented"]["classes"]}
    assert rows["models.Child"]["dit"] == 0
    assert rows["models.Base"]["noc"] == 0


def test_deep_call_component_dag_and_package_cycle_are_iterative() -> None:
    from metrics.logic.call_graph import _longest_component_path

    count = 1200
    components = [{str(index)} for index in range(count)]
    edges = {(str(index), str(index + 1)) for index in range(count - 1)}
    # A forward cross-edge must not merge SCCs or displace the longest chain.
    edges.add(("0", "2"))
    assert len(_longest_component_path(components, edges)) == count

    files = [
        {"name": "module", "path": package, "path_parts": [package],
         "imports": [{"object": target, "path": f"{target}.module", "from_lib": False}]}
        for package, target in (("alpha", "beta"), ("beta", "gamma"), ("gamma", "alpha"))
    ]
    architecture = calculate_graph_metrics(
        {"body": [{"file": file} for file in files]}
    )["architecture"]
    assert architecture["cyclic_package_components"] == [["alpha", "beta", "gamma"]]


def test_semantic_call_targets_disambiguate_duplicate_names() -> None:
    function = lambda name, calls=[]: {"name": name, "metrics": {"cyclomatic_complexity": 1}, "calls": calls}
    graph = {"body": [
        {"file": {"name": "m1", "path": "", "imports": [], "functions": [function("f")]}},
        {"file": {"name": "m2", "path": "", "imports": [], "functions": [function("f")]}},
        {"file": {"name": "consumer", "path": "", "imports": [], "functions": [
            function("run", [
                {"object": "f", "semantic_target": {"module": "m1", "object": "f"}, "args": []},
                {"object": "f", "semantic_target": {"module": "m1", "object": "f"}, "args": []},
                {"object": "f", "semantic_target": {"module": "m2", "object": "f"}, "args": []},
            ])
        ]}},
    ]}
    edges = calculate_graph_metrics(graph)["call_graph"]["heaviest_edges"]
    assert {"caller": "consumer.run", "target": "m1.f", "callsites": 2} in edges
    assert {"caller": "consumer.run", "target": "m2.f", "callsites": 1} in edges


def test_semantic_call_target_does_not_fall_back_to_short_name() -> None:
    graph = {"body": [
        {"file": {"name": "m1", "path": "", "imports": [], "functions": [
            {"name": "f", "metrics": {"cyclomatic_complexity": 1}, "calls": []}
        ]}},
        {"file": {"name": "consumer", "path": "", "imports": [], "functions": [
            {"name": "run", "metrics": {"cyclomatic_complexity": 1}, "calls": [
                {"object": "f", "semantic_target": {"module": "missing", "object": "f"}, "args": []}
            ]}
        ]}},
    ]}

    call_graph = calculate_graph_metrics(graph)["call_graph"]
    assert call_graph["callsites_in_local_edges"] == 0
    assert call_graph["unresolved_callsites"] == 1


def test_legacy_call_without_semantic_target_uses_unambiguous_import_provenance() -> None:
    """Old DTOs remain resolvable even when duplicate short names exist."""
    function = lambda name, calls=[]: {
        "name": name,
        "metrics": {"cyclomatic_complexity": 1},
        "calls": calls,
    }
    graph = {"body": [
        {"file": {"name": "m1", "path": "", "imports": [], "functions": [function("f")]}},
        {"file": {"name": "m2", "path": "", "imports": [], "functions": [function("f")]}},
        {"file": {
            "name": "consumer",
            "path": "",
            "imports": [{
                "object": "f", "asname": "chosen", "path": "m1", "from_lib": False,
            }],
            "functions": [function("run", [{"object": "f", "args": []}])],
        }},
    ]}

    call_graph = calculate_graph_metrics(graph)["call_graph"]
    assert call_graph["heaviest_edges"] == [
        {"caller": "consumer.run", "target": "m1.f", "callsites": 1}
    ]
    assert call_graph["unresolved_callsites"] == 0

    ambiguous = deepcopy(graph)
    ambiguous["body"][2]["file"]["imports"].append({
        "object": "f", "asname": "other", "path": "m2", "from_lib": False,
    })
    ambiguous_call_graph = calculate_graph_metrics(ambiguous)["call_graph"]
    assert ambiguous_call_graph["heaviest_edges"] == []
    assert ambiguous_call_graph["unresolved_callsites"] == 1


def test_modern_v1_missing_semantic_target_does_not_use_legacy_fallback(
    tmp_path: Path,
) -> None:
    function = lambda name, calls=[]: {
        "name": name, "args": [], "return_type": None,
        "metrics": {"cyclomatic_complexity": 1}, "calls": calls,
    }
    body = [
        {"file": {"name": "provider", "path": "", "path_parts": [], "imports": [],
                  "functions": [function("f")]}},
        {"file": {"name": "consumer", "path": "", "path_parts": [],
                  "imports": [{"object": "f", "path": "provider", "from_lib": False}],
                  "functions": [function("run", [{"object": "f", "args": []}])]}},
    ]
    graph_path = tmp_path / "graph.json"
    graph_path.write_text(json.dumps(_v1(body)), encoding="utf-8")

    result = json.loads(calculate_metrics(
        graph_path, tmp_path / "metrics.json"
    ).read_text(encoding="utf-8"))
    call_graph = result["metrics"]["call_graph"]
    assert call_graph["heaviest_edges"] == []
    assert call_graph["unresolved_callsites"] == 1


def test_unversioned_legacy_dto_keeps_unambiguous_fallback() -> None:
    graph = {
        "body": [
            {"file": {"name": "provider", "path": "", "imports": [], "functions": [
                {"name": "f", "metrics": {"cyclomatic_complexity": 1}, "calls": []}
            ]}},
            {"file": {"name": "consumer", "path": "", "imports": [
                {"object": "f", "path": "provider", "from_lib": False}
            ], "functions": [
                {"name": "run", "metrics": {"cyclomatic_complexity": 1},
                 "calls": [{"object": "f", "args": []}]}
            ]}},
        ]
    }

    assert calculate_graph_metrics(graph)["call_graph"]["heaviest_edges"] == [
        {"caller": "consumer.run", "target": "provider.f", "callsites": 1}
    ]


def test_module_definition_shadow_does_not_keep_import_semantic_target() -> None:
    graph = {"body": [
        {"file": {"name": "provider", "path": "", "imports": [], "functions": [
            {"name": "f", "metrics": {"cyclomatic_complexity": 1}, "calls": []}
        ]}},
        {"file": {"name": "consumer", "path": "", "imports": [], "functions": [
            {"name": "f", "metrics": {"cyclomatic_complexity": 1}, "calls": []},
            {"name": "run", "metrics": {"cyclomatic_complexity": 1}, "calls": [
                {"object": "f", "args": []}
            ]},
        ]}},
    ]}
    edges = calculate_graph_metrics(graph)["call_graph"]["heaviest_edges"]
    assert {"caller": "consumer.run", "target": "consumer.f", "callsites": 1} in edges
    assert not any(edge["target"] == "provider.f" for edge in edges)


def test_shadowed_call_without_provenance_is_unresolved_in_modern_dto() -> None:
    graph = _v1([{"file": {
        "name": "consumer", "path": "", "path_parts": [], "imports": [],
        "functions": [
            {"name": "run", "args": [], "return_type": None,
             "metrics": {"cyclomatic_complexity": 1},
             "calls": [{"object": "f", "args": []}]},
        ],
    }}])
    call_graph = calculate_graph_metrics(graph, legacy_resolution=False)["call_graph"]
    assert not any(
        edge["target"] == "provider.f" for edge in call_graph["heaviest_edges"]
    )
    assert call_graph["unresolved_callsites"] == 1


def test_canonical_self_inheritance_and_cycle_descendants_are_permutation_safe() -> None:
    graph = _canonical_metrics_graph()
    graph["nodes"].append({"id": "c:D", "kind": "class", "qualified_name": "m.D"})
    graph["edges"] = [
        {"kind": "inherits", "source_id": "c:A", "target_id": "c:A"},
        {"kind": "inherits", "source_id": "c:B", "target_id": "c:A"},
        {"kind": "inherits", "source_id": "c:B", "target_id": "c:C"},
        {"kind": "inherits", "source_id": "c:C", "target_id": "c:B"},
        {"kind": "inherits", "source_id": "c:D", "target_id": "c:B"},
    ]
    first = calculate_graph_metrics(graph, canonical_objects=True)["object_oriented"]
    permuted = deepcopy(graph)
    permuted["nodes"].reverse()
    permuted["edges"].reverse()
    second = calculate_graph_metrics(permuted, canonical_objects=True)["object_oriented"]
    assert first == second
    rows = {row["class"]: row for row in first["classes"]}
    assert (rows["m.A"]["dit"], rows["m.A"]["noc"]) == (None, 1)
    assert all(rows[name]["dit"] is None for name in ("m.B", "m.C", "m.D"))


def test_canonical_single_self_inheritance_has_unknown_dit_and_no_child() -> None:
    graph = {
        "nodes": [{"id": "c:self", "kind": "class", "qualified_name": "m.C"}],
        "edges": [{"kind": "inherits", "source_id": "c:self", "target_id": "c:self"}],
        "body": [],
    }
    row = calculate_graph_metrics(
        graph, canonical_objects=True
    )["object_oriented"]["classes"][0]
    assert (row["dit"], row["noc"]) == (None, 0)


def test_canonical_duplicate_labels_keep_all_callables_and_classes_distinct() -> None:
    graph = {
        "nodes": [
            {"id": "file:pkg.py", "kind": "file", "qualified_name": "pkg", "path": "pkg.py"},
            {"id": "file:pkg/__init__.py", "kind": "file", "qualified_name": "pkg", "path": "pkg/__init__.py"},
            {"id": "c:one", "kind": "class", "qualified_name": "pkg.C", "parent_id": "file:pkg.py", "path": "pkg.py"},
            {"id": "c:two", "kind": "class", "qualified_name": "pkg.C", "parent_id": "file:pkg/__init__.py", "path": "pkg/__init__.py"},
            {"id": "m:one", "kind": "method", "qualified_name": "pkg.C.work", "parent_id": "c:one", "path": "pkg.py"},
            {"id": "m:two", "kind": "method", "qualified_name": "pkg.C.work", "parent_id": "c:two", "path": "pkg/__init__.py"},
            {"id": "m:duplicate", "kind": "method", "qualified_name": "pkg.C.work", "parent_id": "c:two", "path": "pkg/__init__.py"},
        ],
        "edges": [
            {"kind": "calls", "source_id": "m:one", "target_id": "m:two"},
            {"kind": "calls", "source_id": "m:two", "target_id": "m:duplicate"},
            {"kind": "calls", "source_id": "m:duplicate", "target_id": "m:two"},
        ], "callsites": [], "body": [],
    }
    first = calculate_graph_metrics(graph, canonical_objects=True, canonical_calls=True)
    permuted = deepcopy(graph)
    permuted["nodes"].reverse()
    permuted["edges"].reverse()
    second = calculate_graph_metrics(permuted, canonical_objects=True, canonical_calls=True)
    assert first == second
    calls = first["call_graph"]
    assert (calls["nodes"], calls["edges"], calls["maximum_call_chain_depth"]) == (3, 3, 1)
    assert len(calls["recursive_components"]) == 1
    assert len({row["node"] for row in calls["pagerank_top"]}) == 3
    assert len({row["node"] for row in calls["betweenness_top"]}) == 3
    assert any("file:pkg.py" in row["caller"] for row in calls["heaviest_edges"])
    assert any("file:pkg/__init__.py" in row["target"] for row in calls["heaviest_edges"])
    classes = first["object_oriented"]["classes"]
    assert len(classes) == len({row["class"] for row in classes}) == 2


def test_canonical_longest_chain_uses_unique_labels_not_weights_or_order() -> None:
    graph = {
        "nodes": [
            {"id": "file:consumer.py", "kind": "file", "qualified_name": "consumer", "path": "consumer.py"},
            {"id": "file:pkg.py", "kind": "file", "qualified_name": "pkg", "path": "pkg.py"},
            {"id": "file:pkg/__init__.py", "kind": "file", "qualified_name": "pkg", "path": "pkg/__init__.py"},
            {"id": "fn:run", "kind": "function", "qualified_name": "consumer.run", "parent_id": "file:consumer.py"},
            {"id": "fn:outer", "kind": "function", "qualified_name": "pkg.outer", "parent_id": "file:pkg/__init__.py"},
            {"id": "fn:inner", "kind": "function", "qualified_name": "pkg.inner", "parent_id": "file:pkg/__init__.py"},
            {"id": "fn:duplicate-a", "kind": "function", "qualified_name": "pkg.same", "parent_id": "file:pkg.py"},
            {"id": "fn:duplicate-b", "kind": "function", "qualified_name": "pkg.same", "parent_id": "file:pkg.py"},
        ],
        "edges": [
            {"kind": "calls", "source_id": "fn:run", "target_id": "fn:outer", "weight": 100},
            {"kind": "calls", "source_id": "fn:run", "target_id": "fn:inner", "weight": 1},
        ],
        "callsites": [],
        "body": [],
    }

    first = calculate_graph_metrics(graph, canonical_calls=True)["call_graph"]
    permuted = deepcopy(graph)
    permuted["nodes"].reverse()
    permuted["edges"].reverse()
    second = calculate_graph_metrics(permuted, canonical_calls=True)["call_graph"]

    assert first == second
    assert first["longest_call_chain"] == [
        "consumer.run", "file:pkg/__init__.py.inner"
    ]
    duplicate_labels = {
        label for label in first["isolated_callables"]
        if label.startswith("file:pkg.py.same [")
    }
    assert duplicate_labels == {
        "file:pkg.py.same [fn:duplicate-a]",
        "file:pkg.py.same [fn:duplicate-b]",
    }


def test_canonical_lcom_boundaries_and_rfc_synthetic_targets() -> None:
    graph = {
        "nodes": [
            {"id": "c:none", "kind": "class", "qualified_name": "m.None"},
            {"id": "c:one", "kind": "class", "qualified_name": "m.One"},
            {"id": "c:empty", "kind": "class", "qualified_name": "m.Empty"},
            {"id": "f:one", "kind": "field", "qualified_name": "m.One.value", "parent_id": "c:one"},
            {"id": "f:empty", "kind": "field", "qualified_name": "m.Empty.value", "parent_id": "c:empty"},
            {"id": "m:one", "kind": "method", "qualified_name": "m.One.work", "parent_id": "c:one"},
            {"id": "m:first", "kind": "method", "qualified_name": "m.Empty.first", "parent_id": "c:empty"},
            {"id": "m:second", "kind": "method", "qualified_name": "m.Empty.second", "parent_id": "c:empty"},
            {"id": "m:synthetic", "kind": "method", "qualified_name": "m.Empty.__init__", "parent_id": "c:empty", "synthetic": True},
        ],
        "edges": [
            {"kind": "calls", "source_id": "m:first", "target_id": "m:synthetic"},
            {"kind": "calls", "source_id": "m:synthetic", "target_id": "m:second"},
        ], "body": [],
    }
    rows = {row["class"]: row for row in calculate_graph_metrics(graph, canonical_objects=True)["object_oriented"]["classes"]}
    assert rows["m.None"]["lcom"] is None
    assert rows["m.One"]["lcom"] is None
    assert rows["m.Empty"]["lcom"] == 1.0
    assert rows["m.Empty"]["rfc"] == 3


def test_semantics5_body_mutations_do_not_change_canonical_metrics() -> None:
    graph = _canonical_metrics_graph()
    graph["parser_semantics_version"] = 5
    baseline = calculate_graph_metrics(graph)

    mutated = deepcopy(graph)
    body_file = mutated["body"][0]["file"]
    body_file.update({"path": "wrong", "path_parts": ["wrong"], "metrics": {"noise": 1}})
    body_file["constants"] = []
    body_file["classes"] = []
    changed = calculate_graph_metrics(mutated)
    assert changed["size"] == baseline["size"]
    assert changed["architecture"] == baseline["architecture"]
    assert changed["object_oriented"]["classes"] == baseline["object_oriented"]["classes"]


def test_semantics5_activity_remains_legacy_body_backed() -> None:
    graph = _canonical_metrics_graph()
    graph["parser_semantics_version"] = 5
    baseline = calculate_graph_metrics(graph)["activity"]
    changed = deepcopy(graph)
    file = changed["body"][0]["file"]
    file["imports"] = []
    file["classes"][0]["methods"] = []
    file["calls"] = [{"type": "call", "name": "extra"}]
    assert calculate_graph_metrics(changed)["activity"] != baseline


def test_semantics5_paths_packages_and_order_use_canonical_owners() -> None:
    graph = _canonical_metrics_graph()
    graph["parser_semantics_version"] = 5
    first = calculate_graph_metrics(graph)

    permuted = deepcopy(graph)
    permuted["nodes"].reverse()
    permuted["edges"].reverse()
    second = calculate_graph_metrics(permuted)
    assert second["size"] == first["size"]
    assert second["architecture"] == first["architecture"]
    assert second["object_oriented"] == first["object_oriented"]


def test_semantics4_size_and_package_population_remain_legacy_backed() -> None:
    graph = {
        "parser_semantics_version": 4,
        "body": [{"file": {"name": "legacy", "path": "legacy", "path_parts": ["legacy"],
                            "classes": [{"name": "C", "type": "abstract", "methods": []}],
                            "functions": [], "constants": [], "imports": []}}],
        "nodes": [
            {"id": "file:new.py", "kind": "file", "qualified_name": "new", "path": "new.py"},
            {"id": "method:synthetic", "kind": "method", "qualified_name": "new.C.__init__",
             "parent_id": "class:new", "synthetic": True},
        ],
        "edges": [], "callsites": [], "import_references": [],
    }
    metrics = calculate_graph_metrics(graph)
    assert metrics["size"]["classes"] == 1
    assert metrics["size"]["methods"] == 0
    assert metrics["architecture"]["packages"][0]["package"] == "legacy"
    assert metrics["architecture"]["packages"][0]["classes"] == 1


def test_semantics7_metrics_are_bodyless_and_activity_uses_structural_facts() -> None:
    graph = _canonical_call_graph()
    graph["owner_structural_facts"] = [
        {"owner_id": "file:provider.py", "call_occurrences": 0,
         "direct_import_occurrences": {"project_local": 0, "non_project": 0}},
        {"owner_id": "file:consumer.py", "call_occurrences": 0,
         "direct_import_occurrences": {"project_local": 1, "non_project": 1}},
        {"owner_id": "fn:run", "call_occurrences": 3,
         "direct_import_occurrences": {"project_local": 0, "non_project": 0}},
        {"owner_id": "fn:available", "call_occurrences": 0,
         "direct_import_occurrences": {"project_local": 0, "non_project": 0}},
    ]
    baseline = calculate_graph_metrics(graph)

    assert graph["parser_semantics_version"] == 7
    assert "body" not in graph
    assert baseline["activity"]["calls"] == 3
    assert baseline["activity"]["local_imports"] == 1
    assert baseline["activity"]["external_imports"] == 1

def test_semantics6_and_7_bodyless_payloads_produce_equivalent_metrics() -> None:
    semantics7 = _canonical_call_graph()
    semantics6 = deepcopy(semantics7)
    semantics6["parser_semantics_version"] = 6
    assert calculate_graph_metrics(semantics6) == calculate_graph_metrics(semantics7)


def test_semantics6_activity_zero_denominators_are_floats() -> None:
    graph = {
        "parser_semantics_version": 6,
        "nodes": [{"id": "file:empty.py", "kind": "file", "qualified_name": "empty",
                   "path": "empty.py"}],
        "edges": [], "callsites": [], "import_references": [],
        "owner_structural_facts": [{
            "owner_id": "file:empty.py", "call_occurrences": 0,
            "direct_import_occurrences": {"project_local": 0, "non_project": 0},
        }],
    }
    activity = calculate_graph_metrics(graph)["activity"]
    assert activity["average_calls_per_callable"] == 0.0
    assert activity["average_calls_per_call_owner"] == 0.0
    assert activity["average_methods_per_class"] == 0.0
