import json
from copy import deepcopy
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

import pytest

from metrics import calculate_graph_metrics, calculate_metrics, load_graph
from graph_dto import graph_fingerprint


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
