import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from parser import parse_project, starter


def test_committed_source_matches_complete_graph_v1_golden(tmp_path: Path) -> None:
    fixtures = Path(__file__).resolve().parents[1] / "gpt_work_dir/tests/golden_v1"
    actual_path = parse_project(fixtures / "source", tmp_path / "graph.json")

    actual = json.loads(actual_path.read_text(encoding="utf-8"))
    expected = json.loads((fixtures / "graph.json").read_text(encoding="utf-8"))

    # The committed fixture remains a semantics-v2 compatibility artifact.
    assert actual["body"] == expected["body"]


def test_package_calls_source_matches_complete_graph_v1_golden(tmp_path: Path) -> None:
    fixtures = (
        Path(__file__).resolve().parents[1]
        / "gpt_work_dir/tests/golden_v1/package_calls"
    )
    actual_path = parse_project(fixtures / "source", tmp_path / "graph.json")

    actual = json.loads(actual_path.read_text(encoding="utf-8"))
    expected = json.loads((fixtures / "graph.json").read_text(encoding="utf-8"))

    assert actual["body"] == expected["body"]

    file_ids = {node["id"] for node in actual["nodes"] if node["kind"] == "file"}
    assert file_ids == {
        "file:pkg.py",
        "file:pkg/__init__.py",
        "file:consumer.py",
    }
    import_edges = [edge for edge in actual["edges"] if edge["kind"] == "imports"]
    assert [(edge["source_id"], edge["target_id"]) for edge in import_edges] == [
        ("file:consumer.py", "file:pkg/__init__.py")
    ]
    assert not any(
        edge["source_id"] == "file:pkg/__init__.py"
        and edge["target_id"] == "file:consumer.py"
        for edge in import_edges
    )
    assert any(
        diagnostic["kind"] == "shadowed_module"
        and diagnostic["path"] == "pkg.py"
        for diagnostic in actual["diagnostics"]
    )

    callsites = actual["callsites"]
    assert len(callsites) == 4
    assert len({callsite["caller_id"] for callsite in callsites}) == 1
    assert sorted(callsite["syntactic_depth"] for callsite in callsites) == [0, 0, 0, 1]
    nodes = {node["id"]: node for node in actual["nodes"]}
    run_id = next(
        node_id
        for node_id, node in nodes.items()
        if node["qualified_name"] == "consumer.run"
    )
    assert any(
        edge["kind"] == "contains"
        and edge["source_id"] == "file:consumer.py"
        and edge["target_id"] == run_id
        for edge in actual["edges"]
    )
    call_edges = [edge for edge in actual["edges"] if edge["kind"] == "calls"]
    weights = {
        nodes[edge["target_id"]]["qualified_name"]: edge["weight"]
        for edge in call_edges
    }
    caller_id = callsites[0]["caller_id"]
    assert all(edge["source_id"] == caller_id for edge in call_edges)
    assert weights == {"pkg.outer": 3, "pkg.inner": 1}
    assert sum(edge["weight"] for edge in call_edges) == 4


def test_parse_project_is_atomic_deterministic_and_keeps_starter_semantics(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "sample.py").write_text("def f(x):\n    return x + 1\n", encoding="utf-8")

    first = parse_project(source, tmp_path / "first.json")
    second = parse_project(source, tmp_path / "second.json")

    assert first == first.resolve()
    assert first.read_bytes() == second.read_bytes()
    dto = json.loads(first.read_text(encoding="utf-8"))
    assert dto["schema_version"] == 1
    assert dto["body"] == starter(source)["body"]
    assert dto["nodes"][0]["id"] == "file:sample.py"


def test_canonical_import_references_distinguish_all_static_outcomes(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / "pkg").mkdir(parents=True)
    (source / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (source / "pkg" / "local.py").write_text("value = 1\n", encoding="utf-8")
    (source / "pkg" / "consumer.py").write_text(
        "from .local import value as first, value as second\n"
        "from .missing import value\n"
        "from ..too_high import value\n"
        "import third_party as external\n",
        encoding="utf-8",
    )

    dto = json.loads(parse_project(source, tmp_path / "graph.json").read_text(encoding="utf-8"))
    assert dto["parser_semantics_version"] == 6
    references = [
        item for item in dto["import_references"]
        if item["importer_id"] == "file:pkg/consumer.py"
    ]
    assert [item["resolution"] for item in references].count("exact") == 2
    assert [item["resolution"] for item in references].count("unresolved") == 2
    assert [item["resolution"] for item in references].count("external") == 1
    assert {item["alias"] for item in references if item["resolution"] == "exact"} == {"first", "second"}
    exact = [item for item in references if item["resolution"] == "exact"]
    assert all(item["target_id"] == "file:pkg/local.py" for item in exact)
    import_edges = [edge for edge in dto["edges"] if edge["kind"] == "imports"]
    assert {edge["id"] for edge in import_edges} == {
        f"imports:{item['id']}" for item in dto["import_references"]
        if item["resolution"] == "exact"
    }
    assert len([edge for edge in import_edges if edge["source_id"] == "file:pkg/consumer.py"]) == 2


def test_canonical_imports_include_nested_occurrences_with_stable_unique_ids(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "dependency.py").write_text("value = 1\n", encoding="utf-8")
    (source / "consumer.py").write_text(
        "def run():\n"
        "    import dependency, dependency\n"
        "    if True:\n        from dependency import value\n"
        "class C:\n    import dependency as class_dep\n"
        "    def method(self):\n        import dependency as method_dep\n",
        encoding="utf-8",
    )

    dto = json.loads(parse_project(source, tmp_path / "graph.json").read_text(encoding="utf-8"))
    references = [item for item in dto["import_references"]
                  if item["importer_id"] == "file:consumer.py"]
    assert len(references) == 5
    assert len({item["id"] for item in references}) == 5
    assert all(item["resolution"] == "exact" for item in references)
    assert all(item["target_id"] == "file:dependency.py" for item in references)
    consumer = next(item["file"] for item in dto["body"]
                    if item["file"]["name"] == "consumer")
    assert consumer["imports"] == []


def test_over_root_relative_import_is_unresolved_in_import_and_call_scopes(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / "pkg").mkdir(parents=True)
    (source / "dependency.py").write_text("def f(): pass\n", encoding="utf-8")
    (source / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (source / "pkg" / "consumer.py").write_text(
        "from ..dependency import f\n\ndef run():\n    f()\n",
        encoding="utf-8",
    )

    dto = json.loads(parse_project(source, tmp_path / "graph.json").read_text(encoding="utf-8"))
    reference = next(
        item for item in dto["import_references"]
        if item["importer_id"] == "file:pkg/consumer.py"
    )
    callsite = next(item for item in dto["callsites"] if item["expression"] == "f()")

    assert (reference["level"], reference["resolution"], reference["target_id"]) == (
        2, "unresolved", None,
    )
    assert (callsite["resolution"], callsite["target_id"]) == ("unresolved", None)
    assert not any(
        edge["kind"] == "imports"
        and edge["source_id"] == "file:pkg/consumer.py"
        for edge in dto["edges"]
    )


def test_module_suffix_fallback_is_limited_to_repository_qualified_imports(tmp_path: Path) -> None:
    source = tmp_path / "data"
    (source / "pkg").mkdir(parents=True)
    (source / "util.py").write_text("def f(): pass\n", encoding="utf-8")
    (source / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (source / "pkg" / "relative.py").write_text(
        "from .util import f\n", encoding="utf-8"
    )
    (source / "absolute.py").write_text(
        "from vendor.util import f\nfrom repository.data.util import f as qualified\n",
        encoding="utf-8",
    )

    dto = json.loads(parse_project(source, tmp_path / "graph.json").read_text(encoding="utf-8"))
    absolute = next(
        item for item in dto["import_references"]
        if item["importer_id"] == "file:absolute.py"
        and item["module"] == "vendor.util"
        and item["name"] == "f"
        and item["alias"] is None
    )
    qualified = next(
        item for item in dto["import_references"] if item["alias"] == "qualified"
    )
    assert (absolute["resolution"], absolute["target_id"]) == (
        "external", None,
    )
    relative = next(
        item for item in dto["import_references"]
        if item["importer_id"] == "file:pkg/relative.py"
    )
    assert (relative["resolution"], relative["target_id"]) == ("unresolved", None)
    assert qualified["resolution"] == "exact"
    assert qualified["target_id"] == "file:util.py"


def test_parse_project_requires_paths(tmp_path: Path) -> None:
    with pytest.raises(TypeError):
        parse_project(str(tmp_path), tmp_path / "graph.json")  # type: ignore[arg-type]


def test_parse_project_removes_temporary_file_when_replace_fails(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "sample.py").write_text("value = 1\n", encoding="utf-8")
    target = tmp_path / "graph.json"
    target.write_text("old graph", encoding="utf-8")

    with patch("parser.core.os.replace", side_effect=OSError("injected failure")):
        with pytest.raises(OSError, match="injected failure"):
            parse_project(source, target)

    assert target.read_text(encoding="utf-8") == "old graph"
    assert not list(tmp_path.glob(".graph.json.*"))


def test_public_parser_does_not_import_source_index() -> None:
    assert "parser.logic.source_index" not in sys.modules


def test_package_wins_module_name_collision_and_file_ids_do_not_collide(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / "pkg").mkdir(parents=True)
    (source / "pkg.py").write_text("value = 1\n", encoding="utf-8")
    (source / "pkg" / "__init__.py").write_text("value = 2\n", encoding="utf-8")
    (source / "consumer.py").write_text("import pkg\n", encoding="utf-8")
    dto = json.loads(parse_project(source, tmp_path / "graph.json").read_text(encoding="utf-8"))
    file_ids = {node["id"] for node in dto["nodes"] if node["kind"] == "file"}
    assert {"file:pkg.py", "file:pkg/__init__.py"} <= file_ids
    assert any(edge["kind"] == "imports" and edge["target_id"] == "file:pkg/__init__.py" for edge in dto["edges"])
    assert any(item["kind"] == "shadowed_module" and item["path"] == "pkg.py" for item in dto["diagnostics"])


def test_dotted_import_binds_root_and_alias_and_resolves_deep_package(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / "a" / "b" / "c").mkdir(parents=True)
    (source / "a" / "__init__.py").write_text("", encoding="utf-8")
    (source / "a" / "b" / "__init__.py").write_text("", encoding="utf-8")
    (source / "a" / "b" / "c.py").write_text("def wrong(): pass\n", encoding="utf-8")
    (source / "a" / "b" / "c" / "__init__.py").write_text("def func(): pass\n", encoding="utf-8")
    (source / "consumer.py").write_text(
        "import a.b.c\nimport a.b.c as chosen\n\ndef run():\n    a.b.c.func()\n    chosen.func()\n",
        encoding="utf-8",
    )
    dto = json.loads(
        parse_project(source, tmp_path / "graph.json").read_text(encoding="utf-8")
    )
    consumer = next(
        item["file"] for item in dto["body"] if item["file"]["name"] == "consumer"
    )
    calls = consumer["functions"][0]["calls"]
    assert [call["object"] for call in calls] == ["func", "func"]
    targets = [edge["target_id"] for edge in dto["edges"] if edge["kind"] == "imports"
               and edge["source_id"] == "file:consumer.py"]
    assert targets == ["file:a/b/c/__init__.py", "file:a/b/c/__init__.py"]


def test_from_import_resolves_deep_package_function(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / "a" / "b").mkdir(parents=True)
    (source / "a" / "__init__.py").write_text("", encoding="utf-8")
    (source / "a" / "b" / "__init__.py").write_text(
        "def chosen(): pass\n", encoding="utf-8"
    )
    (source / "consumer.py").write_text(
        "from a.b import chosen as alias\n\ndef run():\n    alias()\n",
        encoding="utf-8",
    )

    dto = json.loads(
        parse_project(source, tmp_path / "graph.json").read_text(encoding="utf-8")
    )
    consumer = next(
        item["file"] for item in dto["body"] if item["file"]["name"] == "consumer"
    )
    assert consumer["functions"][0]["calls"][0]["object"] == "chosen"
    assert any(
        edge["kind"] == "imports"
        and edge["source_id"] == "file:consumer.py"
        and edge["target_id"] == "file:a/b/__init__.py"
        for edge in dto["edges"]
    )


def test_calls_preserve_import_semantic_targets_for_aliases_and_nested_calls(tmp_path: Path) -> None:
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

    dto = json.loads(
        parse_project(source, tmp_path / "graph.json").read_text(encoding="utf-8")
    )
    consumer = next(
        item["file"] for item in dto["body"] if item["file"]["name"] == "consumer"
    )
    calls = consumer["functions"][0]["calls"]
    assert [call["object"] for call in calls] == ["f", "f", "f", "f"]
    assert [call["semantic_target"] for call in calls] == [
        {"module": "m1", "object": "f"},
        {"module": "m1", "object": "f"},
        {"module": "m1", "object": "f"},
        {"module": "m2", "object": "f"},
    ]
    assert calls[0]["args"][0]["value"]["semantic_target"] == {
        "module": "m2", "object": "f"
    }


def test_import_targets_are_suppressed_by_callable_lexical_bindings(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "provider.py").write_text("def f(): pass\n", encoding="utf-8")
    (source / "consumer.py").write_text(
        "from provider import f\n\n"
        "def parameter(f):\n    f()\n\n"
        "def assigned_before():\n    f = lambda: None\n    f()\n\n"
        "def assigned_after():\n    f()\n    f = lambda: None\n\n"
        "def nested_block():\n    if True:\n        f = lambda: None\n    f()\n\n"
        "def local_definition():\n    f()\n    def f():\n        pass\n\n"
        "def loop_target():\n    f()\n    for f in ():\n        pass\n\n"
        "def comprehension_target():\n    [f() for f in ()]\n",
        encoding="utf-8",
    )

    dto = json.loads(
        parse_project(source, tmp_path / "graph.json").read_text(encoding="utf-8")
    )
    consumer = next(
        item["file"] for item in dto["body"] if item["file"]["name"] == "consumer"
    )
    for function in consumer["functions"]:
        assert function["calls"]
        assert all("semantic_target" not in call for call in function["calls"])


def test_from_import_distinguishes_class_methods_from_module_functions(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "pkg.py").write_text(
        "def f(): pass\n\nclass C:\n    @staticmethod\n    def f(): pass\n",
        encoding="utf-8",
    )
    (source / "consumer.py").write_text(
        "from pkg import C as Alias\nfrom pkg import f as imported_f\n\n"
        "def run():\n    Alias.f()\n    imported_f()\n    Alias.missing()\n",
        encoding="utf-8",
    )

    dto = json.loads(
        parse_project(source, tmp_path / "graph.json").read_text(encoding="utf-8")
    )
    consumer = next(
        item["file"] for item in dto["body"] if item["file"]["name"] == "consumer"
    )
    calls = consumer["functions"][0]["calls"]
    assert calls[0]["semantic_target"] == {"module": "pkg", "object": "C.f"}
    assert calls[1]["semantic_target"] == {"module": "pkg", "object": "f"}
    assert "semantic_target" not in calls[2]


def test_module_import_provenance_follows_statement_order(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "provider.py").write_text(
        "def f(): pass\nclass C: pass\nasync def work(): pass\ndef value(): pass\n",
        encoding="utf-8",
    )
    (source / "consumer.py").write_text(
        "from provider import f\nf()\ndef f(): pass\nf()\n"
        "from provider import C\nC()\nclass C: pass\nC()\n"
        "from provider import work\nwork()\nasync def work(): pass\nwork()\n"
        "from provider import value\nvalue()\nvalue = lambda: None\nvalue()\n",
        encoding="utf-8",
    )

    dto = json.loads(parse_project(source, tmp_path / "graph.json").read_text(encoding="utf-8"))
    consumer = next(item["file"] for item in dto["body"] if item["file"]["name"] == "consumer")
    calls = consumer["calls"]
    assert [call.get("semantic_target") for call in calls] == [
        {"module": "provider", "object": "f"}, None,
        {"module": "provider", "object": "C.__init__"}, None,
        {"module": "provider", "object": "work"}, None,
        {"module": "provider", "object": "value"}, None,
    ]


def test_global_write_and_reimports_follow_statement_order(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "first.py").write_text("def f(): pass\n", encoding="utf-8")
    (source / "second.py").write_text("def f(): pass\n", encoding="utf-8")
    (source / "consumer.py").write_text(
        "from first import f\nf()\nfrom first import f\nf()\n"
        "from second import f\nf()\n\ndef run():\n"
        "    global f\n    f()\n    f = lambda: None\n    f()\n",
        encoding="utf-8",
    )

    dto = json.loads(parse_project(source, tmp_path / "graph.json").read_text(encoding="utf-8"))
    consumer = next(item["file"] for item in dto["body"] if item["file"]["name"] == "consumer")
    assert [call["semantic_target"]["module"] for call in consumer["calls"]] == [
        "first", "first", "second",
    ]
    run_calls = next(item for item in consumer["functions"] if item["name"] == "run")["calls"]
    assert run_calls[0]["semantic_target"] == {"module": "second", "object": "f"}
    assert "semantic_target" not in run_calls[1]


def test_canonical_callsites_preserve_legacy_and_emit_exact_aggregates(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "provider.py").write_text(
        "def first(): pass\ndef second(): pass\n"
        "class Synthetic: pass\nclass Real:\n    def __init__(self): pass\n"
        "class Worker:\n    def work(self): pass\n    def again(self):\n        self.work()\n",
        encoding="utf-8",
    )
    (source / "consumer.py").write_text(
        "import os\nfrom provider import first as one, second as two, Synthetic, Real, Worker\n"
        "one()\none()\nSynthetic()\nReal()\nunknown()\nos.getcwd()\n"
        "def shadowed(one):\n    one()\n"
        "async def run(worker: Worker):\n    await one(two())\n    worker.work()\n",
        encoding="utf-8",
    )

    legacy = starter(source)["body"]
    dto = json.loads(parse_project(source, tmp_path / "graph.json").read_text(encoding="utf-8"))
    assert dto["body"] == legacy
    assert not any(item["id"] == "semantic_callsites_transition" for item in dto["diagnostics"])

    consumer_calls = [item for item in dto["callsites"] if item["location"]["path"] == "consumer.py"]
    module_calls = [item for item in consumer_calls if item["caller_id"] == "file:consumer.py"]
    assert len(module_calls) == 6
    repeated = [item for item in module_calls if item["expression"] == "one()"]
    assert len(repeated) == 2
    assert all(item["resolution"] == "exact" for item in repeated)
    assert next(item for item in module_calls if item["expression"] == "unknown()")["resolution"] == "unresolved"
    assert next(item for item in module_calls if item["expression"] == "os.getcwd()")["resolution"] == "external"

    awaited = next(item for item in consumer_calls if item["expression"] == "one(two())")
    nested = next(item for item in consumer_calls if item["expression"] == "two()")
    assert (awaited["awaited"], awaited["syntactic_depth"]) == (True, 0)
    assert (nested["awaited"], nested["syntactic_depth"]) == (False, 1)
    assert awaited["target_id"] != nested["target_id"]
    assert next(item for item in consumer_calls if item["expression"] == "worker.work()")["resolution"] == "exact"
    self_call = next(item for item in dto["callsites"] if item["expression"] == "self.work()")
    assert self_call["resolution"] == "exact"
    assert any(edge["kind"] == "calls" and edge["source_id"] == self_call["caller_id"]
               and edge["target_id"] == self_call["target_id"] for edge in dto["edges"])

    repeated_edge = next(
        edge for edge in dto["edges"]
        if edge["kind"] == "calls" and edge["source_id"] == "file:consumer.py"
        and edge["target_id"] == repeated[0]["target_id"]
    )
    assert repeated_edge["weight"] == 2
    assert not any(edge["kind"] in {"calls", "awaits"} and edge["source_id"] == next(
        item["caller_id"] for item in consumer_calls if item["expression"] == "one()" and item["caller_id"] != "file:consumer.py"
    ) for edge in dto["edges"])

    synthetic_target = next(item["target_id"] for item in module_calls if item["expression"] == "Synthetic()")
    real_target = next(item["target_id"] for item in module_calls if item["expression"] == "Real()")
    synthetic_node = next(item for item in dto["nodes"] if item["id"] == synthetic_target)
    real_node = next(item for item in dto["nodes"] if item["id"] == real_target)
    assert synthetic_node["synthetic"] is True
    assert "synthetic" not in real_node


def test_canonical_callsites_and_call_edges_are_deterministic(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "provider.py").write_text(
        "def outer(value=None): pass\ndef inner(): pass\n", encoding="utf-8"
    )
    (source / "consumer.py").write_text(
        "from provider import outer, inner\n"
        "async def run():\n"
        "    await outer(inner())\n"
        "    outer()\n"
        "    outer()\n",
        encoding="utf-8",
    )

    first = json.loads(
        parse_project(source, tmp_path / "first.json").read_text(encoding="utf-8")
    )
    second = json.loads(
        parse_project(source, tmp_path / "second.json").read_text(encoding="utf-8")
    )

    assert first["callsites"] == second["callsites"]
    first_call_edges = [
        edge for edge in first["edges"] if edge["kind"] in {"calls", "awaits"}
    ]
    second_call_edges = [
        edge for edge in second["edges"] if edge["kind"] in {"calls", "awaits"}
    ]
    assert first_call_edges == second_call_edges
    assert len(first["callsites"]) == 4
    assert sorted(edge["weight"] for edge in first_call_edges) == [1, 1, 2]


def test_canonical_import_calls_respect_comprehension_and_walrus_order(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "provider.py").write_text("def f(): pass\n", encoding="utf-8")
    (source / "consumer.py").write_text(
        "from provider import f\n"
        "def comprehension(values):\n    [f() for f in values]\n"
        "def tuple_order(other):\n"
        "    from provider import f\n    (f(), (f := other))\n    f()\n"
        "def rhs_order():\n"
        "    from provider import f\n    (f := f())\n    f()\n",
        encoding="utf-8",
    )

    dto = json.loads(parse_project(source, tmp_path / "graph.json").read_text(encoding="utf-8"))
    calls = [
        item for item in dto["callsites"]
        if item["location"]["path"] == "consumer.py" and item["expression"] == "f()"
    ]
    calls.sort(key=lambda item: item["location"]["line"])
    assert [item["resolution"] for item in calls] == [
        "dynamic", "exact", "dynamic", "exact", "dynamic",
    ]
    assert [item["target_id"] is not None for item in calls] == [
        False, True, False, True, False,
    ]
    comprehension_caller = calls[0]["caller_id"]
    assert not any(
        edge["kind"] in {"calls", "awaits"}
        and edge["source_id"] == comprehension_caller
        for edge in dto["edges"]
    )


def test_canonical_collection_covers_executable_expression_containers_once(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "provider.py").write_text(
        "def default(): pass\ndef annotation(): pass\ndef make_meta(): pass\n"
        "def marker(): pass\ndef manager(): pass\ndef guard(): pass\ndef hidden(): pass\n",
        encoding="utf-8",
    )
    (source / "consumer.py").write_text(
        "from provider import default, annotation, make_meta, marker, manager, guard, hidden\n"
        "def top(value: annotation() = default(), *, keyword=default()): pass\n"
        "class C(metaclass=make_meta()):\n"
        "    value = marker()\n"
        "    def method(value=default()): pass\n"
        "def run(subject):\n"
        "    with manager():\n        pass\n"
        "    match subject:\n"
        "        case _ if guard():\n            pass\n"
        "    def nested():\n        hidden()\n",
        encoding="utf-8",
    )
    dto = json.loads(parse_project(source, tmp_path / "graph.json").read_text(encoding="utf-8"))
    calls = [item for item in dto["callsites"] if item["location"]["path"] == "consumer.py"]
    expressions = [item["expression"] for item in calls]
    assert expressions.count("default()") == 3
    for expression in ("annotation()", "make_meta()", "marker()", "manager()", "guard()"):
        assert expressions.count(expression) == 1
    assert "hidden()" not in expressions
    assert all(item["resolution"] == "exact" for item in calls)
    assert all(
        item["caller_id"] == "file:consumer.py"
        for item in calls
        if item["expression"] in {"annotation()", "default()", "make_meta()", "marker()"}
    )
    run_caller = next(
        node["id"] for node in dto["nodes"]
        if node["kind"] == "function" and node["qualified_name"] == "consumer.run"
    )
    assert all(
        item["caller_id"] == run_caller
        for item in calls
        if item["expression"] in {"manager()", "guard()"}
    )


def test_function_local_imports_and_declaration_identity_are_exact(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / "pkg").mkdir(parents=True)
    (source / "provider.py").write_text("def f(): pass\n", encoding="utf-8")
    (source / "duplicates.py").write_text(
        "def f(): pass\nf()\ndef f(): pass\nf()\n", encoding="utf-8"
    )
    (source / "pkg.py").write_text("def own(): pass\nown()\n", encoding="utf-8")
    (source / "pkg" / "__init__.py").write_text("def own(): pass\n", encoding="utf-8")
    (source / "consumer.py").write_text(
        "def run():\n    from provider import f as local\n    local()\n"
        "def ordered():\n    local()\n    from provider import f as local\n    local()\n"
        "    local = lambda: None\n    local()\n"
        "import pkg\npkg.own()\n",
        encoding="utf-8",
    )
    dto = json.loads(parse_project(source, tmp_path / "graph.json").read_text(encoding="utf-8"))

    local = next(
        item for item in dto["callsites"]
        if item["expression"] == "local()" and item["location"]["line"] == 3
    )
    assert local["resolution"] == "exact"
    assert next(node for node in dto["nodes"] if node["id"] == local["target_id"])["path"] == "provider.py"
    ordered = sorted(
        (item for item in dto["callsites"] if item["expression"] == "local()" and item["location"]["line"] > 3),
        key=lambda item: item["location"]["line"],
    )
    assert [item["resolution"] for item in ordered] == ["dynamic", "exact", "dynamic"]
    assert [item["target_id"] is not None for item in ordered] == [False, True, False]

    duplicate_calls = sorted(
        (item for item in dto["callsites"] if item["location"]["path"] == "duplicates.py"),
        key=lambda item: item["location"]["line"],
    )
    assert [next(node for node in dto["nodes"] if node["id"] == item["target_id"])["location"]["line"]
            for item in duplicate_calls] == [1, 3]
    shadowed = next(item for item in dto["callsites"] if item["location"]["path"] == "pkg.py")
    imported = next(item for item in dto["callsites"] if item["expression"] == "pkg.own()")
    assert next(node for node in dto["nodes"] if node["id"] == shadowed["target_id"])["path"] == "pkg.py"
    assert next(node for node in dto["nodes"] if node["id"] == imported["target_id"])["path"] == "pkg/__init__.py"


def test_rebinding_and_branch_merges_drop_unproven_exact_targets(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.py").write_text(
        "def f(): pass\nclass Worker:\n    def work(self): pass\n", encoding="utf-8"
    )
    (source / "b.py").write_text(
        "def f(): pass\nclass Worker:\n    def work(self): pass\n", encoding="utf-8"
    )
    (source / "consumer.py").write_text(
        "from a import Worker\n"
        "def reassigned(other):\n    x: Worker\n    x = other\n    x.work()\n"
        "def branched(flag):\n"
        "    if flag:\n        from a import f\n        x = Worker()\n"
        "    else:\n        from b import f\n        from b import Worker as Other\n        x = Other()\n"
        "    f()\n    x.work()\n"
        "def tried():\n"
        "    try:\n        from a import f\n"
        "    except Exception:\n        from b import f\n"
        "    f()\n"
        "def matched(subject):\n"
        "    match subject:\n"
        "        case 1:\n            from a import f\n"
        "        case _:\n            from b import f\n"
        "    f()\n",
        encoding="utf-8",
    )
    dto = json.loads(parse_project(source, tmp_path / "graph.json").read_text(encoding="utf-8"))
    uncertain = [
        item for item in dto["callsites"]
        if item["expression"] in {"f()", "x.work()"}
    ]
    assert len(uncertain) == 5
    assert all(item["resolution"] != "exact" and item["target_id"] is None for item in uncertain)
    uncertain_ids = {item["id"] for item in uncertain}
    assert not any(
        edge["kind"] in {"calls", "awaits"}
        and any(item["id"] in uncertain_ids and item["caller_id"] == edge["source_id"]
                and item.get("target_id") == edge["target_id"] for item in uncertain)
        for edge in dto["edges"]
    )


def test_lambda_defaults_execute_in_outer_scope_but_lambda_body_is_omitted(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "provider.py").write_text(
        "def default(): pass\ndef hidden(): pass\n", encoding="utf-8"
    )
    (source / "consumer.py").write_text(
        "from provider import default, hidden\n"
        "callback = lambda x=default(): hidden()\n",
        encoding="utf-8",
    )
    dto = json.loads(parse_project(source, tmp_path / "graph.json").read_text(encoding="utf-8"))
    calls = [item for item in dto["callsites"] if item["location"]["path"] == "consumer.py"]
    assert [item["expression"] for item in calls] == ["default()"]
    assert calls[0]["caller_id"] == "file:consumer.py"
    assert calls[0]["resolution"] == "exact"


def test_loop_flows_merge_zero_iteration_body_and_else_conservatively(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.py").write_text(
        "def f(): pass\ndef g(): pass\ndef h(): pass\nclass Worker:\n    def work(self): pass\n",
        encoding="utf-8",
    )
    (source / "b.py").write_text("def g(): pass\n", encoding="utf-8")
    (source / "consumer.py").write_text(
        "from a import Worker\n"
        "def run(items, flag):\n"
        "    for item in items:\n"
        "        from a import f\n        x = Worker()\n        f()\n"
        "    f()\n    x.work()\n"
        "    while flag:\n        from a import g\n        g()\n"
        "    else:\n        from b import g\n        g()\n"
        "    g()\n"
        "async def async_run(items):\n"
        "    async for item in items:\n        from a import h\n        h()\n"
        "    h()\n",
        encoding="utf-8",
    )
    dto = json.loads(parse_project(source, tmp_path / "graph.json").read_text(encoding="utf-8"))
    calls = [item for item in dto["callsites"] if item["location"]["path"] == "consumer.py"]
    f_calls = sorted((item for item in calls if item["expression"] == "f()"),
                     key=lambda item: item["location"]["line"])
    g_calls = sorted((item for item in calls if item["expression"] == "g()"),
                     key=lambda item: item["location"]["line"])
    assert len(f_calls) == 2 and f_calls[0]["resolution"] == "exact"
    assert f_calls[1]["resolution"] != "exact"
    assert next(item for item in calls if item["expression"] == "x.work()")["resolution"] != "exact"
    assert len(g_calls) == 3
    assert [item["resolution"] for item in g_calls[:2]] == ["exact", "exact"]
    assert g_calls[0]["target_id"] != g_calls[1]["target_id"]
    assert g_calls[2]["resolution"] != "exact"
    h_calls = sorted((item for item in calls if item["expression"] == "h()"),
                     key=lambda item: item["location"]["line"])
    assert len(h_calls) == 2 and h_calls[0]["resolution"] == "exact"
    assert h_calls[1]["resolution"] != "exact"


def test_all_rebinding_forms_clear_canonical_import_provenance(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "provider.py").write_text(
        "def f(): pass\nclass Worker:\n    def work(self): pass\n", encoding="utf-8"
    )
    (source / "consumer.py").write_text(
        "from provider import f\n"
        "match object():\n    case f if f():\n        pass\n"
        "def except_binding():\n"
        "    from provider import f\n    try:\n        pass\n"
        "    except Exception as f:\n        f()\n"
        "def with_binding(cm):\n"
        "    from provider import f\n    with cm as f:\n        f()\n"
        "def named_binding(other):\n"
        "    from provider import f\n    (f := other)\n    f()\n"
        "def augmented_binding(other):\n"
        "    from provider import f\n    f += other\n    f()\n"
        "def deleted_binding():\n"
        "    from provider import f\n    del f\n    f()\n"
        "def typed_bindings(cm, other):\n"
        "    from provider import Worker\n"
        "    augmented: Worker\n    augmented += other\n    augmented.work()\n"
        "    deleted: Worker\n    del deleted\n    deleted.work()\n"
        "    named: Worker\n    (named := other)\n    named.work()\n"
        "    with_bound: Worker\n    with cm as with_bound:\n        with_bound.work()\n"
        "    except_bound: Worker\n    try:\n        pass\n"
        "    except Exception as except_bound:\n        except_bound.work()\n"
        "def internal_binding(other):\n"
        "    def local(): pass\n    local += other\n    local()\n",
        encoding="utf-8",
    )
    dto = json.loads(parse_project(source, tmp_path / "graph.json").read_text(encoding="utf-8"))
    calls = [
        item for item in dto["callsites"]
        if item["location"]["path"] == "consumer.py" and item["expression"] == "f()"
    ]
    assert len(calls) == 6
    assert all(item["resolution"] != "exact" and item["target_id"] is None for item in calls)
    rebound_calls = [
        item for item in dto["callsites"]
        if item["location"]["path"] == "consumer.py"
        and item["expression"] in {
            "augmented.work()", "deleted.work()", "named.work()",
            "with_bound.work()", "except_bound.work()", "local()",
        }
    ]
    assert len(rebound_calls) == 6
    assert all(
        item["resolution"] != "exact" and item["target_id"] is None
        for item in rebound_calls
    )


def test_with_items_resolve_left_to_right_without_duplicate_context_calls(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "provider.py").write_text(
        "def manager(): pass\nclass Worker:\n    def work(self): pass\n",
        encoding="utf-8",
    )
    (source / "consumer.py").write_text(
        "import provider\nfrom provider import manager, Worker\n"
        "def run():\n"
        "    x = Worker()\n"
        "    with manager() as x, x.work():\n        pass\n"
        "    with manager() as provider, provider.f():\n        pass\n"
        "async def async_run():\n"
        "    x = Worker()\n"
        "    async with manager() as x, x.work():\n        pass\n",
        encoding="utf-8",
    )
    dto = json.loads(parse_project(source, tmp_path / "graph.json").read_text(encoding="utf-8"))
    calls = [item for item in dto["callsites"] if item["location"]["path"] == "consumer.py"]
    assert [item["expression"] for item in calls].count("manager()") == 3
    work = [item for item in calls if item["expression"] == "x.work()"]
    assert len(work) == 2
    assert all(item["resolution"] != "exact" and item["target_id"] is None for item in work)
    imported_member = [item for item in calls if item["expression"] == "provider.f()"]
    assert len(imported_member) == 1
    assert imported_member[0]["resolution"] != "exact" and imported_member[0]["target_id"] is None


def test_except_type_uses_conservative_try_effects_and_is_collected_once(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "provider.py").write_text("def make_error(): pass\n", encoding="utf-8")
    (source / "consumer.py").write_text(
        "def run(replacement):\n"
        "    from provider import make_error\n"
        "    try:\n        make_error = replacement\n"
        "    except make_error():\n        pass\n",
        encoding="utf-8",
    )
    dto = json.loads(parse_project(source, tmp_path / "graph.json").read_text(encoding="utf-8"))
    calls = [item for item in dto["callsites"] if item["expression"] == "make_error()"]
    assert len(calls) == 1
    assert calls[0]["resolution"] != "exact" and calls[0]["target_id"] is None


def test_attribute_rebinding_invalidates_import_root_and_inferred_receiver(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "provider.py").write_text(
        "def f(): pass\nclass Worker:\n    def work(self): pass\n",
        encoding="utf-8",
    )
    (source / "consumer.py").write_text(
        "import provider\nimport provider as deleted_provider\nfrom provider import Worker\n"
        "provider.f = replacement\nprovider.f()\n"
        "del deleted_provider.f\ndeleted_provider.f()\n"
        "x = Worker()\nx.work = replacement\nx.work()\n"
        "y = Worker()\ndel y.work\ny.work()\n",
        encoding="utf-8",
    )
    dto = json.loads(parse_project(source, tmp_path / "graph.json").read_text(encoding="utf-8"))
    calls = [
        item for item in dto["callsites"]
        if item["expression"] in {
            "provider.f()", "deleted_provider.f()", "x.work()", "y.work()"
        }
    ]
    assert len(calls) == 4
    assert all(item["resolution"] != "exact" and item["target_id"] is None for item in calls)


def test_semantics2_object_relations_cover_imports_types_and_field_accesses(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / "pkg").mkdir(parents=True)
    (source / "pkg.py").write_text("class Wrong: pass\n", encoding="utf-8")
    (source / "pkg" / "__init__.py").write_text("class Base: pass\n", encoding="utf-8")
    (source / "types.py").write_text("class Item: pass\n", encoding="utf-8")
    (source / "duplicate.py").write_text("class Item: pass\n", encoding="utf-8")
    (source / "model.py").write_text(
        "from pkg import Base as Parent\nimport types as t\nimport missing as ext\n"
        "class Local: pass\n"
        "class Model(Parent):\n"
        "    items: list[t.Item | 'Local']\n"
        "    external: ext.Value\n"
        "    unknown: Missing\n"
        "    inferred = t.Item()\n"
        "    def read(self):\n"
        "        first = self.items\n"
        "        second = lambda: self.items\n"
        "        def nested(): return self.items\n"
        "        return self.inferred\n",
        encoding="utf-8",
    )
    dto = json.loads(parse_project(source, tmp_path / "graph.json").read_text(encoding="utf-8"))
    assert dto["parser_semantics_version"] == 6
    nodes = {node["id"]: node for node in dto["nodes"]}
    fields = [node for node in nodes.values() if node["kind"] == "field"]
    assert {node["qualified_name"] for node in fields} >= {
        "model.Model.items", "model.Model.external", "model.Model.unknown", "model.Model.inferred"
    }
    references = dto["type_references"]
    assert next(item for item in references if item["role"] == "base")["resolution"] == "exact"
    item_refs = [item for item in references if item["expression"] == "t.Item"]
    assert item_refs and all(nodes[item["target_id"]]["path"] == "types.py" for item in item_refs)
    assert next(item for item in references if item["expression"] == "ext.Value")["resolution"] == "external"
    assert next(item for item in references if item["expression"] == "Missing")["resolution"] == "unresolved"
    assert not any(item["resolution"] == "ambiguous" for item in references)
    access_edges = sorted(
        (edge for edge in dto["edges"] if edge["kind"] == "accesses_field"),
        key=lambda edge: (edge["location"]["line"], edge["location"]["column"]),
    )
    assert [(nodes[edge["target_id"]]["qualified_name"], edge["location"]["line"])
            for edge in access_edges] == [
        ("model.Model.items", 11), ("model.Model.inferred", 14)
    ]


def test_semantics2_infers_instance_field_type_from_constructor_assignment(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "model.py").write_text(
        "class Item:\n    pass\n\n"
        "class Owner:\n"
        "    def __init__(self):\n        self.item = Item()\n\n"
        "    def read(self):\n        return self.item\n",
        encoding="utf-8",
    )

    dto = json.loads(
        parse_project(source, tmp_path / "graph.json").read_text(encoding="utf-8")
    )
    nodes = {node["id"]: node for node in dto["nodes"]}
    field = next(
        node for node in nodes.values()
        if node["kind"] == "field" and node["qualified_name"] == "model.Owner.item"
    )
    item_class = next(
        node for node in nodes.values()
        if node["kind"] == "class" and node["qualified_name"] == "model.Item"
    )
    assert any(
        edge["kind"] == "field_type"
        and edge["source_id"] == field["id"]
        and edge["target_id"] == item_class["id"]
        for edge in dto["edges"]
    )
    assert any(
        edge["kind"] == "accesses_field"
        and nodes[edge["source_id"]]["qualified_name"] == "model.Owner.read"
        and edge["target_id"] == field["id"]
        for edge in dto["edges"]
    )


def test_semantics2_constructor_bindings_shadow_inferred_field_types(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "provider.py").write_text("class Item: pass\n", encoding="utf-8")
    (source / "model.py").write_text(
        "from provider import Item\n"
        "class ParameterShadow:\n"
        "    def __init__(self, Item):\n        self.value = Item()\n"
        "class LocalShadow:\n"
        "    def __init__(self):\n"
        "        self.value = Item()\n"
        "        Item = replacement\n",
        encoding="utf-8",
    )

    dto = json.loads(parse_project(source, tmp_path / "graph.json").read_text(encoding="utf-8"))
    nodes = {node["id"]: node for node in dto["nodes"]}
    fields = {
        node["qualified_name"]: node for node in nodes.values()
        if node["kind"] == "field"
    }
    shadow_fields = {
        fields["model.ParameterShadow.value"]["id"],
        fields["model.LocalShadow.value"]["id"],
    }
    references = [
        item for item in dto["type_references"]
        if item["role"] == "field_type" and item["owner_id"] in shadow_fields
    ]
    assert len(references) == 2
    assert all(
        item["resolution"] == "unresolved" and item["target_id"] is None
        for item in references
    )
    assert not any(
        edge["kind"] == "field_type" and edge["source_id"] in shadow_fields
        for edge in dto["edges"]
    )


def test_semantics2_generic_type_parameters_shadow_imported_types(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "provider.py").write_text(
        "class Item:\n    def __init__(self): pass\n", encoding="utf-8"
    )
    (source / "model.py").write_text(
        "from provider import Item\n"
        "class Owner[Item](Item):\n"
        "    annotated: Item\n"
        "    initialized = Item()\n"
        "    def __init__(self):\n        self.constructed = Item()\n"
        "class MethodOwner:\n"
        "    def __init__[Item](self):\n        self.value = Item()\n",
        encoding="utf-8",
    )

    dto = json.loads(parse_project(source, tmp_path / "graph.json").read_text(encoding="utf-8"))
    nodes = {node["id"]: node for node in dto["nodes"]}
    owners = {
        node["qualified_name"]: node for node in nodes.values()
        if node["kind"] in {"class", "field"}
    }
    affected = {
        owners["model.Owner"]["id"],
        owners["model.Owner.annotated"]["id"],
        owners["model.Owner.initialized"]["id"],
        owners["model.Owner.constructed"]["id"],
        owners["model.MethodOwner.value"]["id"],
    }
    references = [
        item for item in dto["type_references"] if item["owner_id"] in affected
    ]
    assert len(references) == 5
    assert all(
        item["resolution"] == "unresolved" and item["target_id"] is None
        for item in references
    )
    assert not any(
        edge["kind"] in {"inherits", "field_type"}
        and edge["source_id"] in affected
        for edge in dto["edges"]
    )
    item_initializer = next(
        node for node in nodes.values()
        if node["qualified_name"] == "provider.Item.__init__"
    )
    item_calls = [
        item for item in dto["callsites"]
        if item["location"]["path"] == "model.py" and item["expression"] == "Item()"
    ]
    assert len(item_calls) == 3
    assert all(
        item["resolution"] != "exact" and item["target_id"] is None
        for item in item_calls
    )
    assert not any(
        edge["kind"] in {"calls", "awaits"}
        and edge["target_id"] == item_initializer["id"]
        for edge in dto["edges"]
    )


def test_canonical_receiver_type_parameters_shadow_same_module_classes(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "model.py").write_text(
        "class Item:\n"
        "    def run(self): pass\n"
        "def consume[Item](value: Item):\n"
        "    value.run()\n"
        "class Owner[Item]:\n"
        "    def consume(self, value: Item):\n"
        "        value.run()\n"
        "class MethodOwner:\n"
        "    def consume[Item](self, value: Item):\n"
        "        value.run()\n",
        encoding="utf-8",
    )

    dto = json.loads(parse_project(source, tmp_path / "graph.json").read_text(encoding="utf-8"))
    item_run = next(
        node for node in dto["nodes"]
        if node["qualified_name"] == "model.Item.run"
    )
    calls = [
        item for item in dto["callsites"]
        if item["location"]["path"] == "model.py" and item["expression"] == "value.run()"
    ]
    assert len(calls) == 3
    assert all(
        item["resolution"] != "exact" and item["target_id"] is None
        for item in calls
    )
    assert not any(
        edge["kind"] in {"calls", "awaits"}
        and edge["target_id"] == item_run["id"]
        for edge in dto["edges"]
    )


def test_semantics2_nested_declaration_bindings_and_fields_follow_lexical_scope(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "provider.py").write_text("class Item: pass\n", encoding="utf-8")
    (source / "model.py").write_text(
        "from provider import Item\n"
        "class Owner:\n"
        "    def __init__(self):\n"
        "        self.direct = Item()\n"
        "        self.value = Item()\n"
        "        def shadow(value=(Item := factory)):\n            pass\n"
        "        def nested():\n            self.nested = Item()\n",
        encoding="utf-8",
    )

    dto = json.loads(parse_project(source, tmp_path / "graph.json").read_text(encoding="utf-8"))
    nodes = {node["id"]: node for node in dto["nodes"]}
    fields = {
        node["qualified_name"]: node for node in nodes.values() if node["kind"] == "field"
    }
    assert set(fields) == {"model.Owner.direct", "model.Owner.value"}
    references = [
        item for item in dto["type_references"]
        if item["owner_id"] in {fields["model.Owner.direct"]["id"], fields["model.Owner.value"]["id"]}
    ]
    assert len(references) == 2
    assert all(item["resolution"] == "unresolved" for item in references)
    assert not any(
        edge["kind"] == "field_type"
        and edge["source_id"] in {fields["model.Owner.direct"]["id"], fields["model.Owner.value"]["id"]}
        for edge in dto["edges"]
    )


def test_semantics2_local_class_types_follow_declaration_order(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "model.py").write_text(
        "class C(C):\n    self_ref: C\n\nclass C:\n    pass\n\n"
        "class C(C):\n    previous: C\n    future: Future\n\n"
        "class Owner:\n    current: Owner\n    future: Future\n"
        "    def __init__(self):\n        self.inferred = Future()\n\n"
        "class Future:\n    pass\n", encoding="utf-8",
    )
    dto = json.loads(parse_project(source, tmp_path / "graph.json").read_text(encoding="utf-8"))
    nodes = {node["id"]: node for node in dto["nodes"]}
    references = dto["type_references"]
    c_classes = sorted(
        (node for node in nodes.values() if node["kind"] == "class" and node["qualified_name"] == "model.C"),
        key=lambda node: node["location"]["line"],
    )
    bases = sorted((item for item in references if item["role"] == "base"), key=lambda item: item["location"]["line"])
    assert (bases[0]["resolution"], bases[0]["target_id"]) == ("unresolved", None)
    assert bases[1]["target_id"] == c_classes[1]["id"]
    field_refs = {
        (nodes[item["owner_id"]]["qualified_name"], item["expression"]): item
        for item in references if item["role"] == "field_type"
    }
    assert field_refs[("model.C.self_ref", "C")]["resolution"] == "unresolved"
    assert field_refs[("model.C.previous", "C")]["target_id"] == c_classes[1]["id"]
    for key in (("model.C.future", "Future"), ("model.Owner.current", "Owner"),
                ("model.Owner.future", "Future"), ("model.Owner.inferred", "Future")):
        assert field_refs[key]["resolution"] == "unresolved"


def test_semantics2_type_resolution_uses_latest_proven_preceding_binding(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "provider.py").write_text("class Base: pass\n", encoding="utf-8")
    (source / "model.py").write_text(
        "class Before(Late): pass\n"
        "from provider import Base as Late\n"
        "import provider as assigned\nassigned = object()\nclass Assigned(assigned.Base): pass\n"
        "from provider import Base as defined\ndef defined(): pass\nclass Defined(defined): pass\n"
        "from provider import Base as local\nclass local: pass\nclass Local(local): pass\n"
        "from provider import Base as restored\nrestored = object()\n"
        "from provider import Base as restored\nclass Restored(restored): pass\n"
        "from provider import Base as conditional\n"
        "if flag:\n    conditional = object()\nclass Conditional(conditional): pass\n"
        "if flag:\n    from provider import Base as branch_only\n"
        "class BranchOnly(branch_only): pass\n",
        encoding="utf-8",
    )

    dto = json.loads(parse_project(source, tmp_path / "graph.json").read_text(encoding="utf-8"))
    nodes = {node["id"]: node for node in dto["nodes"]}
    bases = {
        nodes[item["owner_id"]]["qualified_name"]: item
        for item in dto["type_references"] if item["role"] == "base"
    }
    assert bases["model.Before"]["resolution"] == "unresolved"
    assert bases["model.Assigned"]["resolution"] == "unresolved"
    assert bases["model.Defined"]["resolution"] == "unresolved"
    assert bases["model.Conditional"]["resolution"] == "unresolved"
    assert bases["model.BranchOnly"]["resolution"] == "unresolved"
    assert nodes[bases["model.Local"]["target_id"]]["qualified_name"] == "model.local"
    assert nodes[bases["model.Restored"]["target_id"]]["qualified_name"] == "provider.Base"


def test_semantics2_field_types_follow_preceding_class_namespace_bindings(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "provider.py").write_text("class Item: pass\n", encoding="utf-8")
    (source / "model.py").write_text(
        "from provider import Item\n"
        "class AnnotatedShadow:\n    Item = object\n    value: Item\n"
        "class ConstructorShadow:\n    Item = object\n"
        "    def __init__(self):\n        self.value = Item()\n"
        "class EarlierField:\n    value: Item\n    Item = object\n"
        "class ConditionalShadow:\n"
        "    if flag:\n        Item = object\n"
        "    value: Item\n",
        encoding="utf-8",
    )

    dto = json.loads(parse_project(source, tmp_path / "graph.json").read_text(encoding="utf-8"))
    nodes = {node["id"]: node for node in dto["nodes"]}
    references = {
        nodes[item["owner_id"]]["qualified_name"]: item
        for item in dto["type_references"] if item["role"] == "field_type"
    }
    assert references["model.AnnotatedShadow.value"]["resolution"] == "unresolved"
    assert references["model.ConstructorShadow.value"]["resolution"] == "unresolved"
    assert references["model.ConditionalShadow.value"]["resolution"] == "unresolved"
    earlier = references["model.EarlierField.value"]
    assert earlier["resolution"] == "exact"
    assert nodes[earlier["target_id"]]["qualified_name"] == "provider.Item"


def test_semantics2_type_wrappers_only_follow_type_arguments(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "model.py").write_text(
        "from typing import Annotated, Literal, Optional\nclass A: pass\nclass B: pass\n"
        "class Owner:\n    annotated: Annotated[A, B]\n    literal: Literal[B]\n"
        "    optional: Optional[A]\n    either: A | B\n", encoding="utf-8",
    )
    dto = json.loads(parse_project(source, tmp_path / "graph.json").read_text(encoding="utf-8"))
    nodes = {node["id"]: node for node in dto["nodes"]}
    topology = [
        (nodes[item["owner_id"]]["qualified_name"], item["expression"],
         nodes[item["target_id"]]["qualified_name"] if item["target_id"] else None)
        for item in dto["type_references"] if item["role"] == "field_type"
    ]
    assert topology == [
        ("model.Owner.annotated", "A", "model.A"),
        ("model.Owner.optional", "A", "model.A"),
        ("model.Owner.either", "A", "model.A"),
        ("model.Owner.either", "B", "model.B"),
    ]
def test_semantics3_complexity_facts_exactly_reproduce_legacy_rich_flow(tmp_path: Path) -> None:
    from metrics.logic.complexity import metrics_from_facts

    source = tmp_path / "source"
    source.mkdir()
    (source / "flow.py").write_text(
        "async def flow(self, xs, flag):\n"
        "    try:\n"
        "        if flag and len(xs) > 1:\n"
        "            return [await self.run(x) for x in xs if x]\n"
        "        match xs:\n"
        "            case []: raise ValueError()\n"
        "            case _: pass\n"
        "    except Exception:\n"
        "        def nested():\n            return self.hidden\n"
        "        return self.fallback\n",
        encoding="utf-8",
    )
    graph = json.loads(parse_project(source, tmp_path / "graph.json").read_text(encoding="utf-8"))
    node = next(item for item in graph["nodes"] if item["kind"] == "function")
    legacy = graph["body"][0]["file"]["functions"][0]["metrics"]
    assert graph["parser_semantics_version"] == 6
    assert metrics_from_facts(node["complexity_facts"]) == legacy
    assert "hidden" not in legacy["self_attribute_accesses"]


def test_semantics3_structural_locations_and_scope_boundaries_match_legacy(tmp_path: Path) -> None:
    from metrics.logic.complexity import metrics_from_facts

    source = tmp_path / "source"
    source.mkdir()
    (source / "edges.py").write_text(
        "async def edges(self, items):\n"
        "    async for item in items:\n"
        "        values = [value for value in item if value]\n"
        "    try:\n"
        "        pass\n"
        "    except* ValueError:\n"
        "        pass\n"
        "    def nested():\n"
        "        if self.hidden: return 1\n"
        "    class Local:\n"
        "        def method(self): return self.hidden\n"
        "    ignored = lambda value: value if value else 0\n",
        encoding="utf-8",
    )
    graph = json.loads(parse_project(source, tmp_path / "graph.json").read_text(encoding="utf-8"))
    node = next(item for item in graph["nodes"] if item["kind"] == "function")
    facts = node["complexity_facts"]
    legacy = graph["body"][0]["file"]["functions"][0]["metrics"]

    assert metrics_from_facts(facts) == legacy
    # Legacy comprehensions contribute 1 + filter_count (plus depth cognitively).
    assert legacy["cyclomatic_complexity"] == 5
    assert legacy["cognitive_complexity"] == 7
    assert legacy["max_nesting"] == 2
    assert [item["kind"] for item in facts["controls"]] == [
        "async_for", "comprehension", "try_star", "exception_handler",
    ]
    comprehension = facts["controls"][1]
    assert comprehension["parent_index"] == 0
    assert comprehension["location"] == {"path": "edges.py", "line": 3, "column": 17}
    assert legacy["self_attribute_accesses"] == []


def test_semantics5_emits_occurrence_level_constants_with_unique_ids(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "constants.py").write_text(
        "A = B = 1\nA = A = 2\nC: int\nD = factory()\n",
        encoding="utf-8",
    )

    graph = json.loads(parse_project(source, tmp_path / "graph.json").read_text(encoding="utf-8"))
    constants = [node for node in graph["nodes"] if node["kind"] == "constant"]
    legacy = graph["body"][0]["file"]["constants"]

    assert [item["name"] for item in legacy] == ["A", "B", "A", "A", "C"]
    assert [item["qualified_name"].rsplit(".", 1)[-1] for item in constants] == ["A", "B", "A", "A", "C"]
    assert len({item["id"] for item in constants}) == 5
    assert all(item["parent_id"] == "file:constants.py" for item in constants)
    assert [item["qualified_name"].rsplit(".", 1)[-1] for item in constants] == [
        item["name"] for item in legacy
    ]


def test_semantics5_class_kind_matches_legacy_class_type(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "classes.py").write_text(
        "from abc import ABC, abstractmethod\nfrom dataclasses import dataclass\nfrom enum import Enum\n"
        "class Plain: pass\n@dataclass\nclass Data: pass\nclass Choice(Enum): A = 1\n"
        "class Abstract(ABC):\n @abstractmethod\n def work(self): pass\n"
        "class Inherited(Abstract): pass\nclass Implemented(Abstract):\n def work(self): pass\n",
        encoding="utf-8",
    )
    graph = json.loads(parse_project(source, tmp_path / "graph.json").read_text(encoding="utf-8"))
    canonical = {
        node["qualified_name"].rsplit(".", 1)[-1]: node["class_kind"]
        for node in graph["nodes"] if node["kind"] == "class"
    }
    legacy = {item["name"]: item["type"] for item in graph["body"][0]["file"]["classes"]}

    assert canonical == legacy == {
        "Plain": "class", "Data": "dataclass", "Choice": "enum",
        "Abstract": "abstract", "Inherited": "abstract", "Implemented": "class",
    }


def test_semantics6_structural_facts_exactly_mirror_legacy_activity_owners(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "local.py").write_text("def inner(): pass\n", encoding="utf-8")
    (source / "sample.py").write_text(
        "import local\nimport third_party\nouter(local.inner())\n"
        "class Empty: pass\n"
        "class Real:\n    def method(self):\n        import local\n        outer(local.inner())\n"
        "def function():\n    outer(local.inner())\n"
        "Empty()\n",
        encoding="utf-8",
    )
    graph = json.loads(parse_project(source, tmp_path / "graph.json").read_text(encoding="utf-8"))

    def count_calls(calls):
        def count(call):
            return 1 + sum(
                count(value)
                for argument in call.get("args", []) if isinstance(argument, dict)
                for value in (argument.get("value"),)
                if isinstance(value, dict) and value.get("type") == "call"
            )
        return sum(count(call) for call in calls if isinstance(call, dict))

    facts = {item["owner_id"]: item for item in graph["owner_structural_facts"]}
    nodes = {item["id"]: item for item in graph["nodes"]}
    sample = next(item["file"] for item in graph["body"] if item["file"]["name"] == "sample")
    expected_calls = {"file:sample.py": count_calls(sample["calls"])}
    expected_calls.update({
        next(node_id for node_id, node in nodes.items() if node["qualified_name"] == f"sample.{item['name']}"):
            count_calls(item["calls"])
        for item in sample["functions"]
    })
    for class_item in sample["classes"]:
        for method in class_item["methods"]:
            owner = next(node_id for node_id, node in nodes.items()
                         if node["qualified_name"] == f"sample.{class_item['name']}.{method['name']}")
            expected_calls[owner] = count_calls(method["calls"])

    assert {owner: facts[owner]["call_occurrences"] for owner in expected_calls} == expected_calls
    assert facts["file:sample.py"]["direct_import_occurrences"] == {
        "project_local": 1, "non_project": 1,
    }
    assert set(facts) == {
        node_id for node_id, node in nodes.items()
        if node["kind"] == "file"
        or (node["kind"] in {"function", "method"} and not node.get("synthetic"))
    }
    assert not any(nodes[owner].get("synthetic") for owner in facts)
