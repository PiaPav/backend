import json
from copy import deepcopy
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

import pytest

from metrics import calculate_graph_metrics, calculate_metrics, load_graph


def _graph() -> dict:
    return {
        "body": [
            {"file": {"name": "a", "path": "pkg", "path_parts": ["pkg"], "imports": [], "functions": [{"name": "f", "args": [], "return_type": None, "metrics": {"cyclomatic_complexity": 1}, "calls": [{"object": "g", "args": []}]}]}},
            {"file": {"name": "b", "path": "pkg", "path_parts": ["pkg"], "imports": [], "calls": [{"object": "print", "args": []}]}},
        ]
    }


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


def test_nontrivial_project_matches_legacy_parser_and_metrics(tmp_path: Path) -> None:
    from gpt_work_dir.graph_metrics.calculator import calculate_graph_metrics as legacy_metrics
    from gpt_work_dir.parser.logic.main import starter as legacy_starter
    from parser import starter as new_starter

    package = tmp_path / "project" / "package"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("from .models import Child\n", encoding="utf-8")
    (package / "helpers.py").write_text(
        "def decorate(value):\n    return value\n\ndef repeated(value):\n    return decorate(decorate(value))\n",
        encoding="utf-8",
    )
    (package / "models.py").write_text(
        "from .helpers import repeated\n\nclass Base:\n    def process(self, value):\n        return repeated(value)\n\nclass Child(Base):\n    async def process(self, value):\n        try:\n            if value:\n                return repeated(repeated(value))\n            raise ValueError('missing')\n        except ValueError:\n            return await self.fallback(value)\n\n    async def fallback(self, value):\n        return value\n",
        encoding="utf-8",
    )

    project = package.parent
    graph = new_starter(project)
    assert graph == legacy_starter(project)
    assert calculate_graph_metrics(graph) == legacy_metrics(graph)


def test_no_runtime_cross_package_or_legacy_imports() -> None:
    root = Path(__file__).resolve().parents[1]
    for package, forbidden in (("parser", ("gpt_work_dir", "metrics")), ("metrics", ("gpt_work_dir", "parser"))):
        for path in (root / package).rglob("*.py"):
            if path.name.startswith("test_"):
                continue
            text = path.read_text(encoding="utf-8")
            assert all(f"import {name}" not in text and f"from {name}" not in text for name in forbidden)
