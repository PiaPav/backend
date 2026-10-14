import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from parser import parse_project, starter


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
