import json
import ast
from copy import deepcopy
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

import pytest

from metrics import calculate_graph_metrics, calculate_metrics, load_graph
from graph_dto import graph_fingerprint
from parser import parse_project


def _v3_metrics(graph: dict) -> dict:
    return calculate_graph_metrics(
        graph, canonical_mode=True, legacy_resolution=False,
        canonical_objects=True, canonical_calls=True,
    )


def test_semantics3_complexity_consumers_use_facts_by_node_id(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "model.py").write_text(
        "class Worker:\n"
        "    def run(self, flag):\n"
        "        if flag:\n            return self.run(False)\n"
        "        return 0\n",
        encoding="utf-8",
    )
    graph = json.loads(parse_project(source, tmp_path / "graph.json").read_text(encoding="utf-8"))
    envelope = json.loads(calculate_metrics(tmp_path / "graph.json", tmp_path / "metrics.json").read_text(encoding="utf-8"))
    assert envelope["metrics_semantics_version"] == 4
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


def test_semantics3_synthetic_constructor_has_no_complexity_identity(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "model.py").write_text(
        "class Empty:\n    pass\n\ndef make():\n    return Empty()\n",
        encoding="utf-8",
    )
    graph = json.loads(parse_project(source, tmp_path / "graph.json").read_text(encoding="utf-8"))
    synthetic = next(node for node in graph["nodes"] if node.get("synthetic"))
    assert "complexity_facts" not in synthetic
    metrics = _v3_metrics(graph)
    assert metrics["code_quality"]["analyzed_callables"] == 1
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


def test_committed_graph_matches_complete_metrics_v2_golden(tmp_path: Path) -> None:
    fixtures = Path(__file__).resolve().parents[1] / "gpt_work_dir/tests/golden_v1"
    actual_path = calculate_metrics(fixtures / "graph.json", tmp_path / "metrics.json")

    actual = json.loads(actual_path.read_text(encoding="utf-8"))
    expected = json.loads((fixtures / "metrics.json").read_text(encoding="utf-8"))

    assert actual == expected


def test_package_calls_graph_matches_complete_metrics_v2_golden(tmp_path: Path) -> None:
    fixtures = (
        Path(__file__).resolve().parents[1]
        / "gpt_work_dir/tests/golden_v1/package_calls"
    )
    actual_path = calculate_metrics(fixtures / "graph.json", tmp_path / "metrics.json")

    actual = json.loads(actual_path.read_text(encoding="utf-8"))
    expected = json.loads((fixtures / "metrics.json").read_text(encoding="utf-8"))

    assert actual == expected

    metrics = actual["metrics"]
    assert metrics["size"]["files"] == 3
    assert metrics["size"]["directories"] == 1
    assert metrics["size"]["functions"] == 4
    assert metrics["activity"]["calls"] == 4
    assert metrics["activity"]["local_imports"] == 1
    assert metrics["activity"]["average_calls_per_callable"] == 1.0
    assert metrics["activity"]["average_calls_per_call_owner"] == 1.0

    dependencies = metrics["dependency_graph"]
    assert dependencies["nodes"] == 3
    assert dependencies["edges"] == 1
    assert dependencies["density"] == 0.1667
    assert dependencies["average_fan_in"] == 0.3333
    assert dependencies["average_fan_out"] == 0.3333
    assert dependencies["isolated_files"] == ["file:pkg.py"]
    assert dependencies["highest_fan_in"] == {
        "degree": 1,
        "files": ["file:pkg/__init__.py"],
    }
    assert dependencies["highest_fan_out"] == {
        "degree": 1,
        "files": ["consumer"],
    }

    call_graph = metrics["call_graph"]
    assert call_graph["nodes"] == 4
    assert call_graph["edges"] == 2
    assert call_graph["callsites_in_local_edges"] == 4
    assert call_graph["maximum_syntactic_call_nesting"] == 2
    assert call_graph["local_resolution_rate"] == 1.0
    assert call_graph["classified_callsite_rate"] == 1.0
    assert {
        (edge["caller"], edge["target"], edge["callsites"])
        for edge in call_graph["heaviest_edges"]
    } >= {
        ("consumer.run", "file:pkg/__init__.py.outer", 3),
        ("consumer.run", "file:pkg/__init__.py.inner", 1),
    }


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


def test_canonical_v3_module_calls_are_full_call_graph_owners(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / "pkg").mkdir(parents=True)
    (source / "provider.py").write_text("def available(): pass\n", encoding="utf-8")
    (source / "consumer.py").write_text(
        "from provider import available, missing\nimport external_package as ext\n"
        "available()\nmissing()\next.run()\n",
        encoding="utf-8",
    )
    (source / "pkg.py").write_text("unknown_file()\n", encoding="utf-8")
    (source / "pkg" / "__init__.py").write_text("unknown_package()\n", encoding="utf-8")
    graph_path = parse_project(source, tmp_path / "graph.json")
    graph = json.loads(graph_path.read_text(encoding="utf-8"))

    missing = next(item for item in graph["callsites"] if item["expression"] == "missing()")
    assert (missing["resolution"], missing["target_id"]) == ("unresolved", None)
    call_graph = calculate_graph_metrics(graph, canonical_calls=True)["call_graph"]
    assert (call_graph["external_or_builtin_callsites"], call_graph["unresolved_callsites"]) == (1, 3)
    assert call_graph["callsites_in_local_edges"] == 1
    assert call_graph["local_resolution_rate"] == 0.2
    assert call_graph["classified_callsite_rate"] == 0.4
    assert call_graph["node_kinds"] == {"file": 3, "function": 1}
    assert call_graph["nodes"] == 4
    assert call_graph["edges"] == 1
    assert "consumer.__module__" in call_graph["entrypoints"]
    assert call_graph["longest_call_chain"] == ["consumer.__module__", "provider.available"]
    assert call_graph["heaviest_edges"] == [{
        "caller": "consumer.__module__", "target": "provider.available", "callsites": 1,
    }]
    assert "file:pkg.py.__module__" in call_graph["isolated_callables"]
    assert "file:pkg/__init__.py.__module__" in call_graph["isolated_callables"]
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


def test_metrics_production_has_no_parser_import_ast() -> None:
    root = Path(__file__).parent
    for path in root.rglob("*.py"):
        if path.name.startswith("test_"): continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
        imported += [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        assert not any(name == "parser" or name.startswith("parser.") for name in imported)


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

    with patch("metrics.core.os.replace", side_effect=OSError("injected failure")):
        with pytest.raises(OSError, match="injected failure"):
            calculate_metrics(graph_path, target)

    assert target.read_text(encoding="utf-8") == "old metrics"
    assert not list(tmp_path.glob(".metrics.json.*"))


def test_loader_accepts_real_legacy_graph_fixture() -> None:
    fixture = (
        Path(__file__).resolve().parents[1]
        / "gpt_work_dir/tests/project1/graph/graph.json"
    )

    graph = load_graph(fixture)

    assert graph["body"]


def test_nontrivial_legacy_graph_matches_legacy_metrics() -> None:
    from gpt_work_dir.graph_metrics.calculator import calculate_graph_metrics as legacy_metrics

    fixture = Path(__file__).resolve().parents[1] / "gpt_work_dir/tests/project1/graph/graph.json"
    graph = json.loads(fixture.read_text(encoding="utf-8"))
    current, legacy = calculate_graph_metrics(graph), legacy_metrics(graph)
    # The selected path among equal-length chains is now deterministic.
    current["call_graph"].pop("longest_call_chain")
    legacy["call_graph"].pop("longest_call_chain")
    assert current == legacy


def test_no_runtime_cross_package_or_legacy_imports() -> None:
    root = Path(__file__).resolve().parents[1]
    for package, forbidden in (("parser", ("gpt_work_dir", "metrics")), ("metrics", ("gpt_work_dir", "parser"))):
        for path in (root / package).rglob("*.py"):
            if path.name.startswith("test_"):
                continue
            text = path.read_text(encoding="utf-8")
            assert all(f"import {name}" not in text and f"from {name}" not in text for name in forbidden)


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


def test_real_import_package_call_uses_package_initializer_on_collision(tmp_path: Path) -> None:
    from parser import parse_project

    source = tmp_path / "source"
    (source / "pkg").mkdir(parents=True)
    (source / "pkg.py").write_text("def chosen(): return 'wrong'\n", encoding="utf-8")
    (source / "pkg" / "__init__.py").write_text("def chosen(): return 'right'\n", encoding="utf-8")
    (source / "consumer.py").write_text(
        "import pkg\n\ndef run():\n    return pkg.chosen()\n", encoding="utf-8"
    )

    graph_path = parse_project(source, tmp_path / "graph.json")
    result = json.loads(
        calculate_metrics(graph_path, tmp_path / "metrics.json").read_text(encoding="utf-8")
    )
    assert {"caller": "consumer.run", "target": "file:pkg/__init__.py.chosen", "callsites": 1} \
        in result["metrics"]["call_graph"]["heaviest_edges"]


def test_dotted_import_call_uses_deep_package_initializer_on_collision(tmp_path: Path) -> None:
    from parser import parse_project

    source = tmp_path / "source"
    (source / "a" / "b" / "c").mkdir(parents=True)
    (source / "a" / "__init__.py").write_text("", encoding="utf-8")
    (source / "a" / "b" / "__init__.py").write_text("", encoding="utf-8")
    (source / "a" / "b" / "c.py").write_text("def func(): pass\n", encoding="utf-8")
    (source / "a" / "b" / "c" / "__init__.py").write_text("def func(): pass\n", encoding="utf-8")
    (source / "consumer.py").write_text(
        "import a.b.c\n\ndef run():\n    return a.b.c.func()\n", encoding="utf-8"
    )

    graph_path = parse_project(source, tmp_path / "graph.json")
    result = json.loads(
        calculate_metrics(graph_path, tmp_path / "metrics.json").read_text(encoding="utf-8")
    )
    assert {"caller": "consumer.run", "target": "file:a/b/c/__init__.py.func", "callsites": 1} \
        in result["metrics"]["call_graph"]["heaviest_edges"]


@pytest.mark.parametrize(
    "statement, call",
    [
        ("import a.b.c as alias", "alias.func()"),
        ("from a.b.c import func as alias", "alias()"),
    ],
)
def test_deep_import_aliases_disambiguate_duplicate_callable_names(
    tmp_path: Path, statement: str, call: str
) -> None:
    from parser import parse_project

    source = tmp_path / "source"
    (source / "a" / "b" / "c").mkdir(parents=True)
    (source / "a" / "__init__.py").write_text("", encoding="utf-8")
    (source / "a" / "b" / "__init__.py").write_text("", encoding="utf-8")
    (source / "a" / "b" / "c" / "__init__.py").write_text("def func(): pass\n", encoding="utf-8")
    (source / "other.py").write_text("def func(): pass\n", encoding="utf-8")
    (source / "consumer.py").write_text(
        f"{statement}\n\ndef run():\n    {call}\n", encoding="utf-8"
    )

    graph_path = parse_project(source, tmp_path / "graph.json")
    result = json.loads(calculate_metrics(graph_path, tmp_path / "metrics.json").read_text(encoding="utf-8"))
    assert {"caller": "consumer.run", "target": "a.b.c.func", "callsites": 1} in \
        result["metrics"]["call_graph"]["heaviest_edges"]


def test_semantic_call_targets_disambiguate_aliases_and_nested_repeated_calls(tmp_path: Path) -> None:
    from parser import parse_project

    source = tmp_path / "source"
    source.mkdir()
    (source / "m1.py").write_text("def f(value=None): pass\n", encoding="utf-8")
    (source / "m2.py").write_text("def f(value=None): pass\n", encoding="utf-8")
    (source / "consumer.py").write_text(
        "from m1 import f as first\nfrom m2 import f as second\n"
        "import m1 as one\nimport m2 as two\n\ndef run():\n"
        "    first(second())\n    first()\n    one.f()\n    two.f()\n",
        encoding="utf-8",
    )

    result = json.loads(calculate_metrics(
        parse_project(source, tmp_path / "graph.json"), tmp_path / "metrics.json"
    ).read_text(encoding="utf-8"))
    edges = result["metrics"]["call_graph"]["heaviest_edges"]
    assert {"caller": "consumer.run", "target": "m1.f", "callsites": 3} in edges
    assert {"caller": "consumer.run", "target": "m2.f", "callsites": 2} in edges


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


def test_module_definition_shadow_does_not_keep_import_semantic_target(
    tmp_path: Path,
) -> None:
    from parser import parse_project

    source = tmp_path / "source"
    source.mkdir()
    (source / "provider.py").write_text("def f(): pass\n", encoding="utf-8")
    (source / "consumer.py").write_text(
        "from provider import f\n\ndef f():\n    pass\n\ndef run():\n    f()\n",
        encoding="utf-8",
    )

    result = json.loads(calculate_metrics(
        parse_project(source, tmp_path / "graph.json"), tmp_path / "metrics.json"
    ).read_text(encoding="utf-8"))
    edges = result["metrics"]["call_graph"]["heaviest_edges"]
    assert {"caller": "consumer.run", "target": "consumer.f", "callsites": 1} in edges
    assert not any(edge["target"] == "provider.f" for edge in edges)


@pytest.mark.parametrize(
    ("provider_source", "consumer_source", "expected_target"),
    [
        (
            "class C: pass\n",
            "from provider import C\n\nclass C:\n    pass\n\ndef run():\n    C()\n",
            "consumer.C.__init__",
        ),
        (
            "async def work(): pass\n",
            "from provider import work\n\nasync def work():\n    pass\n\n"
            "async def run():\n    await work()\n",
            "consumer.work",
        ),
    ],
)
def test_module_class_and_async_definition_shadows_import_target(
    tmp_path: Path,
    provider_source: str,
    consumer_source: str,
    expected_target: str,
) -> None:
    from parser import parse_project

    source = tmp_path / "source"
    source.mkdir()
    (source / "provider.py").write_text(provider_source, encoding="utf-8")
    (source / "consumer.py").write_text(consumer_source, encoding="utf-8")

    result = json.loads(calculate_metrics(
        parse_project(source, tmp_path / "graph.json"), tmp_path / "metrics.json"
    ).read_text(encoding="utf-8"))
    edges = result["metrics"]["call_graph"]["heaviest_edges"]
    assert any(edge["target"] == expected_target for edge in edges)
    assert not any(edge["target"].startswith("provider.") for edge in edges)


def test_global_write_does_not_keep_import_provenance(tmp_path: Path) -> None:
    from parser import parse_project

    source = tmp_path / "source"
    source.mkdir()
    (source / "provider.py").write_text("def f(): pass\n", encoding="utf-8")
    (source / "consumer.py").write_text(
        "from provider import f\n\ndef local_callable():\n    pass\n\n"
        "def run():\n    global f\n    f = local_callable\n    f()\n",
        encoding="utf-8",
    )

    graph_path = parse_project(source, tmp_path / "graph.json")
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    consumer = next(
        item["file"] for item in graph["body"] if item["file"]["name"] == "consumer"
    )
    run = next(item for item in consumer["functions"] if item["name"] == "run")
    assert "semantic_target" not in run["calls"][0]

    result = json.loads(calculate_metrics(
        graph_path, tmp_path / "metrics.json"
    ).read_text(encoding="utf-8"))
    call_graph = result["metrics"]["call_graph"]
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
