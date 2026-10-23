import json
from copy import deepcopy
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

import pytest

from graph_dto import graph_fingerprint, validate_graph_v1
from metrics import calculate_graph_metrics, calculate_metrics, load_graph
from metrics.logic.projections import MetricsGraphProjection


def _location(path: str, line: int = 1) -> dict:
    return {"path": path, "line": line, "column": 0}


def _facts(path: str, line: int = 1, *, controls: list[dict] | None = None) -> dict:
    start = _location(path, line)
    end = {"path": path, "line": line + 4, "column": 0}
    return {
        "span": {"start": start, "end": end},
        "is_async": False,
        "controls": controls or [],
        "occurrences": [],
    }


def _node(identifier: str, kind: str, name: str, path: str, *,
          parent_id: str | None = None, line: int = 1, **extra: object) -> dict:
    result = {
        "id": identifier, "kind": kind, "qualified_name": name,
        "parent_id": parent_id, "path": path, "location": _location(path, line),
        **extra,
    }
    if kind in {"function", "method"} and extra.get("synthetic") is not True:
        result["complexity_facts"] = _facts(path, line)
    return result


def _edge(identifier: str, kind: str, source: str, target: str, **extra: object) -> dict:
    return {
        "id": identifier, "kind": kind, "source_id": source,
        "target_id": target, **extra,
    }


def _graph(*, semantics: int = 7) -> dict:
    nodes = [
        _node("file:pkg/a.py", "file", "pkg.a", "pkg/a.py"),
        _node("file:pkg/b.py", "file", "pkg.b", "pkg/b.py"),
        _node("file:app/c.py", "file", "app.c", "app/c.py"),
        _node("class:A", "class", "pkg.a.A", "pkg/a.py", parent_id="file:pkg/a.py", class_kind="class"),
        _node("class:B", "class", "pkg.b.B", "pkg/b.py", parent_id="file:pkg/b.py", class_kind="abstract"),
        _node("class:C", "class", "app.c.C", "app/c.py", parent_id="file:app/c.py", class_kind="class"),
        _node("field:A.x", "field", "pkg.a.A.x", "pkg/a.py", parent_id="class:A"),
        _node("method:A.one", "method", "pkg.a.A.one", "pkg/a.py", parent_id="class:A", line=2),
        _node("method:A.two", "method", "pkg.a.A.two", "pkg/a.py", parent_id="class:A", line=7),
        _node("method:B.work", "method", "pkg.b.B.work", "pkg/b.py", parent_id="class:B", line=2),
        _node("method:C.work", "method", "app.c.C.work", "app/c.py", parent_id="class:C", line=2),
        _node("method:C.__init__", "method", "app.c.C.__init__", "app/c.py", parent_id="class:C", synthetic=True),
    ]
    edges = [
        *[
            _edge(f"contains:{target}", "contains", source, target)
            for source, target in (
                ("file:pkg/a.py", "class:A"), ("class:A", "field:A.x"),
                ("class:A", "method:A.one"), ("class:A", "method:A.two"),
                ("file:pkg/b.py", "class:B"), ("class:B", "method:B.work"),
                ("file:app/c.py", "class:C"), ("class:C", "method:C.work"),
                ("class:C", "method:C.__init__"),
            )
        ],
        _edge("imports:ab", "imports", "file:pkg/a.py", "file:pkg/b.py", location=_location("pkg/a.py")),
        _edge("imports:bc", "imports", "file:pkg/b.py", "file:app/c.py", location=_location("pkg/b.py")),
        _edge("inherits:B:A", "inherits", "class:B", "class:A"),
        _edge("inherits:C:B", "inherits", "class:C", "class:B"),
        _edge("field:A.x:B", "field_type", "field:A.x", "class:B"),
        _edge("access:A.one:x", "accesses_field", "method:A.one", "field:A.x"),
        _edge("calls:one:work", "calls", "method:A.one", "method:B.work", weight=2),
        _edge("calls:one:self", "calls", "method:A.one", "method:A.one", weight=1),
        _edge("calls:two:c", "calls", "method:A.two", "method:C.work", weight=1),
    ]
    callsites = [
        _call("call:1", "method:A.one", "method:B.work", depth=0),
        _call("call:2", "method:A.one", "method:B.work", depth=2),
        _call("call:3", "method:A.one", "method:A.one", depth=0),
        _call("call:4", "method:A.two", "method:C.work", depth=0),
        _call("call:5", "method:A.two", status="external"),
        _call("call:6", "method:A.two", status="unresolved"),
    ]
    imports = [
        _import("ab", "file:pkg/a.py", "pkg.b", "file:pkg/b.py", "pkg/a.py"),
        _import("bc", "file:pkg/b.py", "app.c", "file:app/c.py", "pkg/b.py"),
        _import("external", "file:app/c.py", "requests", None, "app/c.py", status="external"),
    ]
    facts = [
        {"owner_id": identifier, "call_occurrences": calls,
         "direct_import_occurrences": {"project_local": local, "non_project": external}}
        for identifier, calls, local, external in (
            ("file:pkg/a.py", 1, 2, 0), ("file:pkg/b.py", 0, 1, 0),
            ("file:app/c.py", 0, 0, 1),
        )
    ]
    facts.extend(
        {"owner_id": identifier, "call_occurrences": calls}
        for identifier, calls in (
            ("method:A.one", 3), ("method:A.two", 3),
            ("method:B.work", 0), ("method:C.work", 0),
        )
    )
    graph = {
        "schema_version": 1, "parser_semantics_version": semantics,
        "project": {"fingerprint": ""}, "nodes": nodes, "edges": edges,
        "callsites": callsites, "type_references": [
            _type_ref("base:B:A", "class:B", "base", "class:A", "pkg/b.py"),
            _type_ref("base:C:B", "class:C", "base", "class:B", "app/c.py"),
            _type_ref("field:A.x:B", "field:A.x", "field_type", "class:B", "pkg/a.py"),
        ],
        "import_references": imports, "owner_structural_facts": facts,
        "diagnostics": [],
    }
    if semantics == 6:
        graph["body"] = []
    graph["project"]["fingerprint"] = graph_fingerprint(graph)
    return graph


def _call(identifier: str, caller: str, target: str | None = None, *,
          status: str = "exact", depth: int = 0) -> dict:
    return {
        "id": identifier, "caller_id": caller, "expression": f"{identifier}()",
        "location": _location("pkg/a.py"), "resolution": status,
        "target_id": target, "candidate_ids": [], "syntactic_depth": depth,
        "awaited": False,
    }


def _import(identifier: str, importer: str, name: str, target: str | None,
            path: str, *, status: str = "exact") -> dict:
    return {
        "id": identifier, "importer_id": importer, "kind": "import",
        "module": "", "name": name, "alias": None, "level": 0,
        "location": _location(path), "resolution": status,
        "target_id": target, "candidate_ids": [],
    }


def _type_ref(identifier: str, owner: str, role: str, target: str, path: str) -> dict:
    return {
        "id": identifier, "owner_id": owner, "role": role,
        "expression": target, "location": _location(path), "resolution": "exact",
        "target_id": target, "candidate_ids": [],
    }


def _write_graph(path: Path, graph: dict) -> None:
    path.write_text(json.dumps(graph), encoding="utf-8")


def _refingerprint(graph: dict) -> dict:
    graph["project"]["fingerprint"] = graph_fingerprint(graph)
    return graph


def test_unversioned_input_is_rejected_with_migration_message(tmp_path: Path) -> None:
    path = tmp_path / "graph.json"
    _write_graph(path, {"body": []})
    with pytest.raises(ValueError, match="Unversioned graphs.*regenerate"):
        load_graph(path)


@pytest.mark.parametrize("semantics", range(1, 6))
def test_historical_semantics_are_rejected_by_metrics_gate(tmp_path: Path, semantics: int) -> None:
    graph = _graph(semantics=7)
    graph["parser_semantics_version"] = semantics
    graph.pop("body", None)
    _refingerprint(graph)
    message = rf"Unsupported parser_semantics_version: {semantics}; metrics supports 6 and 7 only"
    with pytest.raises(ValueError, match=message):
        calculate_graph_metrics(graph)
    path = tmp_path / "graph.json"
    _write_graph(path, graph)
    with pytest.raises(ValueError, match=message):
        load_graph(path)


@pytest.mark.parametrize("semantics", [[6], {"version": 6}, True])
def test_non_integer_semantics_are_rejected_by_metrics_gate(
    tmp_path: Path, semantics: object,
) -> None:
    graph = _graph()
    graph["parser_semantics_version"] = semantics
    _refingerprint(graph)
    message = "Unsupported parser_semantics_version"
    with pytest.raises(ValueError, match=message):
        calculate_graph_metrics(graph)
    path = tmp_path / "graph.json"
    _write_graph(path, graph)
    with pytest.raises(ValueError, match=message):
        load_graph(path)
    with pytest.raises(ValueError, match=message):
        calculate_metrics(path, tmp_path / "metrics.json")


def test_semantics6_optional_body_is_ignored_by_fingerprint_and_metrics() -> None:
    bodyless = _graph(semantics=6)
    bodyless.pop("body")
    _refingerprint(bodyless)
    with_body = deepcopy(bodyless)
    with_body["body"] = [{"arbitrary": [1, {"value": "ignored"}]}]
    _refingerprint(with_body)
    validate_graph_v1(bodyless)
    validate_graph_v1(with_body)
    assert graph_fingerprint(bodyless) == graph_fingerprint(with_body)
    assert calculate_graph_metrics(bodyless) == calculate_graph_metrics(with_body)


def test_semantics7_is_accepted_and_rejects_body() -> None:
    graph = _graph()
    validate_graph_v1(graph)
    assert calculate_graph_metrics(graph)["size"]["files"] == 3
    graph["body"] = []
    _refingerprint(graph)
    with pytest.raises(ValueError, match="body is not allowed"):
        calculate_graph_metrics(graph)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (b"[", "Invalid graph JSON"),
        (b"[]", "Graph root must be a JSON object"),
        (json.dumps({"schema_version": 2}).encode(), "Unsupported graph schema_version"),
    ],
)
def test_bad_json_root_and_schema_are_rejected(tmp_path: Path, payload: bytes, message: str) -> None:
    path = tmp_path / "graph.json"
    path.write_bytes(payload)
    with pytest.raises(ValueError, match=message):
        load_graph(path)


def test_future_semantics_is_rejected(tmp_path: Path) -> None:
    graph = _graph()
    graph["parser_semantics_version"] = 8
    _refingerprint(graph)
    path = tmp_path / "graph.json"
    _write_graph(path, graph)
    with pytest.raises(ValueError, match="Unsupported parser_semantics_version"):
        load_graph(path)


def test_rejection_preserves_existing_output_and_creates_no_temporary(tmp_path: Path) -> None:
    source = tmp_path / "bad.json"
    source.write_text("[", encoding="utf-8")
    output = tmp_path / "metrics.json"
    output.write_bytes(b"existing")
    with pytest.raises(ValueError):
        calculate_metrics(source, output)
    assert output.read_bytes() == b"existing"
    assert not list(tmp_path.glob(".metrics.json.*"))


def test_file_api_is_deterministic_atomic_and_has_path_contract(tmp_path: Path) -> None:
    source = tmp_path / "graph.json"
    _write_graph(source, _graph())
    output = tmp_path / "nested" / "metrics.json"
    first = calculate_metrics(source, output)
    first_bytes = first.read_bytes()
    second = calculate_metrics(source, output)
    envelope = json.loads(second.read_text(encoding="utf-8"))
    assert first == second == output.resolve()
    assert first_bytes == second.read_bytes()
    assert first_bytes == (json.dumps(envelope, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    assert envelope["metrics_semantics_version"] == 4
    assert not list(output.parent.glob(".metrics.json.*"))
    with pytest.raises(TypeError, match="pathlib.Path"):
        calculate_metrics(str(source), output)  # type: ignore[arg-type]


def test_replace_failure_preserves_output_and_cleans_temporary(tmp_path: Path) -> None:
    source = tmp_path / "graph.json"
    output = tmp_path / "metrics.json"
    _write_graph(source, _graph())
    output.write_bytes(b"existing")
    with patch("metrics.logic.serialization.os.replace", side_effect=OSError("failure")):
        with pytest.raises(OSError, match="failure"):
            calculate_metrics(source, output)
    assert output.read_bytes() == b"existing"
    assert not list(tmp_path.glob(".metrics.json.*"))


def test_aggregate_builds_exactly_one_projection() -> None:
    graph = _graph()
    with patch.object(MetricsGraphProjection, "from_graph", wraps=MetricsGraphProjection.from_graph) as factory:
        calculate_graph_metrics(graph)
    factory.assert_called_once_with(graph)


def test_projection_is_deeply_immutable_detached_and_canonical_only() -> None:
    graph = _graph()
    projection = MetricsGraphProjection.from_graph(graph)
    assert not hasattr(projection, "files")
    assert not hasattr(projection, "module_ids")
    graph["nodes"][0]["qualified_name"] = "changed"
    graph["callsites"][0]["expression"] = "changed()"
    graph["edges"].clear()
    assert projection.nodes_by_id["file:pkg/a.py"]["qualified_name"] == "pkg.a"
    assert projection.callsites[0]["expression"] == "call:1()"
    assert projection.directed_file_import_graph.edges
    with pytest.raises(TypeError):
        projection.nodes_by_id["new"] = {}  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        projection.callsites = ()  # type: ignore[misc]


def test_metrics_are_independent_of_canonical_collection_order() -> None:
    graph = _graph()
    expected = calculate_graph_metrics(graph)
    permuted = deepcopy(graph)
    for collection in (
        "nodes", "edges", "callsites", "type_references",
        "import_references", "owner_structural_facts",
    ):
        permuted[collection].reverse()
    _refingerprint(permuted)
    assert calculate_graph_metrics(permuted) == expected


def test_specialized_gateways_prefer_projection_and_validate_without_it() -> None:
    from metrics.logic.call_graph import calculate_call_graph_metrics
    from metrics.logic.object_metrics import calculate_object_metrics
    from metrics.logic.quality import calculate_quality_metrics, callable_metrics

    graph = _graph()
    projection = MetricsGraphProjection.from_graph(graph)
    gateways = (calculate_call_graph_metrics, calculate_object_metrics,
                calculate_quality_metrics, callable_metrics)
    invalid = {"schema_version": 99}
    for gateway in gateways:
        expected = gateway(graph, projection=projection)
        assert gateway(invalid, projection=projection) == expected
        with pytest.raises(ValueError):
            gateway(invalid)


def test_size_activity_hybrid_denominator_and_import_occurrences() -> None:
    metrics = calculate_graph_metrics(_graph())
    assert metrics["size"] == {
        "directories": 2, "files": 3, "classes": 3, "abstract_classes": 1,
        "dataclasses": 0, "functions": 0, "methods": 4, "fields": 1,
        "constants": 0,
    }
    activity = metrics["activity"]
    assert activity == {
        "calls": 7, "local_imports": 3, "external_imports": 1,
        "average_calls_per_callable": 1.5,
        "average_calls_per_call_owner": 1.4,
        "average_methods_per_class": 1.3333,
    }
    assert metrics["dependency_graph"]["edges"] == 2


def test_zero_denominators_are_zero() -> None:
    graph = _graph()
    roots = {"file:pkg/a.py"}
    graph["nodes"] = [item for item in graph["nodes"] if item["id"] in roots]
    graph["edges"] = []
    graph["callsites"] = []
    graph["type_references"] = []
    graph["import_references"] = []
    graph["owner_structural_facts"] = [{
        "owner_id": "file:pkg/a.py", "call_occurrences": 0,
        "direct_import_occurrences": {"project_local": 0, "non_project": 0},
    }]
    _refingerprint(graph)
    metrics = calculate_graph_metrics(graph)
    assert metrics["activity"]["average_calls_per_callable"] == 0.0
    assert metrics["activity"]["average_methods_per_class"] == 0.0
    assert metrics["dependency_graph"]["density"] == 0.0


def test_import_direction_density_components_cycles_and_bridges() -> None:
    graph = _graph()
    metrics = calculate_graph_metrics(graph)
    dependencies = metrics["dependency_graph"]
    assert dependencies["highest_fan_out"] == {"degree": 1, "files": ["file:pkg/a.py", "file:pkg/b.py"]}
    assert dependencies["highest_fan_in"] == {"degree": 1, "files": ["file:app/c.py", "file:pkg/b.py"]}
    assert dependencies["density"] == 0.3333
    assert dependencies["weakly_connected_components"] == 1
    assert metrics["architecture"]["articulation_files"] == ["file:pkg/b.py"]
    assert len(metrics["architecture"]["bridge_dependencies"]) == 2

    graph["edges"].append(_edge("imports:ca", "imports", "file:app/c.py", "file:pkg/a.py", location=_location("app/c.py")))
    graph["import_references"].append(_import("ca", "file:app/c.py", "pkg.a", "file:pkg/a.py", "app/c.py"))
    graph["owner_structural_facts"][2]["direct_import_occurrences"]["project_local"] = 1
    _refingerprint(graph)
    metrics = calculate_graph_metrics(graph)
    assert metrics["dependency_graph"]["cyclic_components"] == [["file:app/c.py", "file:pkg/a.py", "file:pkg/b.py"]]
    assert metrics["architecture"]["cyclic_package_components"] == [["app", "pkg"]]


def test_call_multiplicity_classification_recursion_chain_and_rankings() -> None:
    call_graph = calculate_graph_metrics(_graph())["call_graph"]
    assert (call_graph["nodes"], call_graph["edges"], call_graph["callsites_in_local_edges"]) == (5, 3, 4)
    assert (call_graph["external_or_builtin_callsites"], call_graph["unresolved_callsites"]) == (1, 1)
    assert call_graph["heaviest_edges"][0] == {
        "caller": "pkg.a.A.one", "target": "pkg.b.B.work", "callsites": 2,
    }
    assert call_graph["recursive_components"] == [["pkg.a.A.one"]]
    assert call_graph["maximum_call_chain_depth"] == 1
    assert call_graph["maximum_syntactic_call_nesting"] == 3
    assert call_graph["pagerank_top"]
    assert call_graph["betweenness_top"]
    assert call_graph["risk_top"]


def test_call_chain_and_ranking_ties_are_deterministic() -> None:
    graph = _graph()
    first = calculate_graph_metrics(graph)["call_graph"]
    permuted = deepcopy(graph)
    permuted["nodes"].reverse()
    permuted["edges"].reverse()
    permuted["callsites"].reverse()
    _refingerprint(permuted)
    second = calculate_graph_metrics(permuted)["call_graph"]
    assert second["longest_call_chain"] == first["longest_call_chain"]
    assert second["pagerank_top"] == first["pagerank_top"]
    assert second["risk_top"] == first["risk_top"]


def test_object_metrics_cover_dit_noc_cbo_rfc_lcom_and_wmc() -> None:
    graph = _graph()
    control = {
        "kind": "if", "parent_index": None, "location": _location("pkg/a.py", 3),
        "operand_count": 0, "case_count": 0, "filter_count": 0,
    }
    next(item for item in graph["nodes"] if item["id"] == "method:A.one")["complexity_facts"]["controls"] = [control]
    _refingerprint(graph)
    rows = {
        row["class"]: row
        for row in calculate_graph_metrics(graph)["object_oriented"]["classes"]
    }
    assert (rows["pkg.a.A"]["dit"], rows["pkg.b.B"]["dit"], rows["app.c.C"]["dit"]) == (0, 1, 2)
    assert (rows["pkg.a.A"]["noc"], rows["pkg.b.B"]["noc"]) == (1, 1)
    assert rows["pkg.a.A"] == {
        "class": "pkg.a.A", "wmc": 3, "cbo": 2, "rfc": 4,
        "lcom": 1.0, "dit": 0, "noc": 1,
    }
    assert rows["app.c.C"]["rfc"] == 1
    assert rows["app.c.C"]["lcom"] is None


def test_inheritance_cycle_and_descendant_have_unknown_depth() -> None:
    graph = _graph()
    graph["edges"].append(_edge("inherits:A:C", "inherits", "class:A", "class:C"))
    graph["type_references"].append(_type_ref("base:A:C", "class:A", "base", "class:C", "pkg/a.py"))
    _refingerprint(graph)
    rows = calculate_graph_metrics(graph)["object_oriented"]["classes"]
    assert all(row["dit"] is None for row in rows)


def test_synthetic_targets_count_for_rfc_but_not_declared_methods_or_wmc() -> None:
    graph = _graph()
    graph["edges"].append(_edge("calls:A.two:init", "calls", "method:A.two", "method:C.__init__", weight=1))
    graph["callsites"].append(_call("call:synthetic", "method:A.two", "method:C.__init__"))
    graph["owner_structural_facts"][4]["call_occurrences"] += 1
    _refingerprint(graph)
    rows = {row["class"]: row for row in calculate_graph_metrics(graph)["object_oriented"]["classes"]}
    assert rows["pkg.a.A"]["rfc"] == 5
    assert rows["app.c.C"]["wmc"] == 1
    assert calculate_graph_metrics(graph)["size"]["methods"] == 4


def test_duplicate_display_labels_are_disambiguated_by_ids() -> None:
    graph = _graph()
    one = next(item for item in graph["nodes"] if item["id"] == "method:A.one")
    work = next(item for item in graph["nodes"] if item["id"] == "method:B.work")
    work["qualified_name"] = one["qualified_name"]
    _refingerprint(graph)
    call_graph = calculate_graph_metrics(graph)["call_graph"]
    labels = {item["caller"] for item in call_graph["heaviest_edges"]} | {
        item["target"] for item in call_graph["heaviest_edges"]
    }
    assert "pkg.a.A.one [method:A.one]" in labels
    assert "pkg.a.A.one [method:B.work]" in labels


def test_semantics6_and_7_canonical_equivalents_have_equal_metrics() -> None:
    v6 = _graph(semantics=6)
    v6["body"] = [{"different": True}]
    _refingerprint(v6)
    v7 = _graph(semantics=7)
    assert calculate_graph_metrics(v6) == calculate_graph_metrics(v7)
    assert v6["project"]["fingerprint"] != v7["project"]["fingerprint"]
