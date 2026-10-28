import ast
from copy import deepcopy
from pathlib import Path

import pytest

from graph_dto import graph_fingerprint
from metrics import calculate_graph_metrics
from metrics.test_core import _graph
from views import materialize_metrics_profile, project_metrics_view, validate_metrics_view_v1
from views.metrics_contract import AGGREGATE_POLICY, OBJECT_INTERPRETATION_POLICY, OBJECT_TOPOLOGY_POLICY
from views.registry import metrics_profile_metadata
from views.testdata.representative_metrics_v2 import build_representative_metrics_v2


def _source() -> dict:
    graph = _graph()
    return {"schema_version": 1, "metrics_semantics_version": 4,
            "input": {"graph_schema_version": 1, "graph_fingerprint": graph_fingerprint(graph)},
            "metrics": calculate_graph_metrics(graph)}


def test_overview_is_an_exact_recursive_whitelist_and_detached() -> None:
    source = _source(); source["metrics"]["size"]["future"] = {"secret": 1}
    view = project_metrics_view(source, profile_id="metrics.overview", profile_version=1)
    assert set(view["payload"]["metrics"]["size"]) == {"directories", "files", "classes", "abstract_classes", "dataclasses", "functions", "methods", "fields", "constants"}
    before = deepcopy(view)
    source["metrics"]["size"]["files"] = 999
    assert view == before
    view["payload"]["metrics"]["size"]["files"] = 888
    assert source["metrics"]["size"]["files"] == 999


def test_architecture_copies_every_selected_value_without_normalizing_lists() -> None:
    source = _source()
    view = materialize_metrics_profile(source, profile_id="metrics.architecture", profile_version=1)
    assert view["payload"]["metrics"]["dependency_graph"] == source["metrics"]["dependency_graph"]
    assert view["payload"]["metrics"]["architecture"] == source["metrics"]["architecture"]
    assert view["payload"]["metrics"]["activity"] == {key: source["metrics"]["activity"][key] for key in ("local_imports", "external_imports")}


def test_registry_returns_fresh_copies() -> None:
    first = metrics_profile_metadata("metrics.overview", 1); first["preserves"].clear()
    assert metrics_profile_metadata("metrics.overview", 1)["preserves"]


def test_omitted_values_do_not_affect_fingerprint_but_selected_values_do() -> None:
    source = _source(); first = project_metrics_view(source, profile_id="metrics.overview", profile_version=1)
    source["metrics"]["code_quality"]["average_cyclomatic_complexity"] += 1
    sibling = project_metrics_view(source, profile_id="metrics.overview", profile_version=1)
    assert sibling["view_fingerprint"] == first["view_fingerprint"]
    source["metrics"]["size"]["files"] += 1
    changed = project_metrics_view(source, profile_id="metrics.overview", profile_version=1)
    assert changed["view_fingerprint"] != first["view_fingerprint"]


def _assert_exact_tree(actual: object, expected: object) -> None:
    assert type(actual) is type(expected)
    if isinstance(expected, dict):
        assert actual.keys() == expected.keys()
        for key in expected:
            _assert_exact_tree(actual[key], expected[key])
    elif isinstance(expected, list):
        assert len(actual) == len(expected)
        for actual_item, expected_item in zip(actual, expected):
            _assert_exact_tree(actual_item, expected_item)
    else:
        assert actual == expected


def test_every_overview_whitelisted_path_preserves_exact_value_and_type() -> None:
    source = _source()
    projected = project_metrics_view(source, profile_id="metrics.overview", profile_version=1)["payload"]["metrics"]
    for section, values in projected.items():
        for field, value in values.items():
            _assert_exact_tree(value, source["metrics"][section][field])


def test_architecture_is_deeply_detached_and_extensions_do_not_leak() -> None:
    source = _source()
    source["extension"] = {"secret": [1]}
    source["metrics"]["architecture"]["packages"][0]["extension"] = {"secret": [2]}
    view = project_metrics_view(source, profile_id="metrics.architecture", profile_version=1)
    before = deepcopy(view)
    source["metrics"]["architecture"]["packages"][0]["package"] = "changed"
    assert view == before
    view["payload"]["metrics"]["architecture"]["packages"][0]["package"] = "view-only"
    assert source["metrics"]["architecture"]["packages"][0]["package"] == "changed"
    assert "extension" not in view
    assert "extension" not in view["payload"]["metrics"]["architecture"]["packages"][0]


def test_source_identity_is_selected_but_unselected_extensions_are_omitted_from_fingerprint() -> None:
    source = _source()
    first = project_metrics_view(source, profile_id="metrics.overview", profile_version=1)
    source["extension"] = {"future": True}
    omitted = project_metrics_view(source, profile_id="metrics.overview", profile_version=1)
    assert omitted["view_fingerprint"] == first["view_fingerprint"]
    source["input"]["graph_fingerprint"] = "f" * 64
    selected = project_metrics_view(source, profile_id="metrics.overview", profile_version=1)
    assert selected["source"]["graph_fingerprint"] == "f" * 64
    assert selected["view_fingerprint"] != first["view_fingerprint"]


def test_projectors_do_not_import_metrics_core() -> None:
    projection_dir = Path(__file__).with_name("projections")
    for filename in ("metrics_overview.py", "metrics_architecture.py", "metrics_quality.py",
                     "metrics_objects.py", "metrics_aggregate.py"):
        tree = ast.parse((projection_dir / filename).read_text(encoding="utf-8"))
        imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        imports += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
        assert all(name != "metrics" and not name.startswith("metrics.") for name in imports)


def test_aggregate_is_exact_recursive_whitelist_detached_and_extension_free() -> None:
    source = _source()
    source["metrics"]["size"]["extension"] = {"secret": [1]}
    view = project_metrics_view(source, profile_id="metrics.aggregate", profile_version=1)
    projected = view["payload"]["metrics"]
    assert sum(1 for section in projected.values() for _ in _integer_leaves(section)) == 27
    assert all(type(value) is int for section in projected.values() for value in _integer_leaves(section))
    _assert_selected_leaves_equal_source(projected, source["metrics"])
    assert "extension" not in projected["size"]
    assert view["payload"]["aggregate_policy"] == AGGREGATE_POLICY
    before = deepcopy(view)
    source["metrics"]["code_quality"]["exceptions"]["raise_statements"] += 1
    assert view == before
    view["payload"]["metrics"]["size"]["files"] += 1
    assert source["metrics"]["size"]["files"] != view["payload"]["metrics"]["size"]["files"]


def _integer_leaves(value: object):
    if isinstance(value, dict):
        for child in value.values():
            yield from _integer_leaves(child)
    else:
        yield value


def _assert_selected_leaves_equal_source(projected: dict, source: dict) -> None:
    for key, value in projected.items():
        if isinstance(value, dict):
            _assert_selected_leaves_equal_source(value, source[key])
        else:
            assert type(value) is type(source[key])
            assert value == source[key]


def test_aggregate_fingerprint_tracks_only_selected_content() -> None:
    source = _source()
    first = project_metrics_view(source, profile_id="metrics.aggregate", profile_version=1)
    source["metrics"]["activity"]["average_calls_per_callable"] += 1
    assert project_metrics_view(source, profile_id="metrics.aggregate", profile_version=1)["view_fingerprint"] == first["view_fingerprint"]
    source["metrics"]["activity"]["calls"] += 1
    assert project_metrics_view(source, profile_id="metrics.aggregate", profile_version=1)["view_fingerprint"] != first["view_fingerprint"]


@pytest.mark.parametrize("version", [True, 0, 2, "1"])
def test_aggregate_dispatch_has_no_version_fallback(version: object) -> None:
    with pytest.raises(ValueError):
        project_metrics_view(_source(), profile_id="metrics.aggregate", profile_version=version)  # type: ignore[arg-type]


def test_quality_is_exact_detached_and_has_consistent_sidecars() -> None:
    source = _source()
    expected = deepcopy(source["metrics"]["code_quality"])
    view = project_metrics_view(source, profile_id="metrics.quality", profile_version=1)
    payload = view["payload"]
    _assert_exact_tree(payload["metrics"]["code_quality"], expected)
    assert payload["metrics"]["size"] == {
        "functions": source["metrics"]["size"]["functions"],
        "methods": source["metrics"]["size"]["methods"],
    }
    descriptor = payload["truncation_metadata"]["rankings"]["metrics.code_quality.largest_callables"]
    assert descriptor["total_matching"] == expected["analyzed_callables"]
    assert descriptor["returned_count"] == len(expected["largest_callables"])
    before = deepcopy(view)
    source["metrics"]["code_quality"]["largest_callables"][0]["lines"] += 1
    assert view == before


def test_quality_extensions_are_recursively_omitted() -> None:
    source = _source()
    source["metrics"]["code_quality"]["extension"] = True
    source["metrics"]["code_quality"]["largest_callables"][0]["extension"] = True
    projected = project_metrics_view(source, profile_id="metrics.quality", profile_version=1)["payload"]["metrics"]["code_quality"]
    assert "extension" not in projected
    assert "extension" not in projected["largest_callables"][0]


def test_objects_is_exact_recursive_whitelist_and_detached() -> None:
    source = _source()
    source["metrics"]["object_oriented"]["extension"] = True
    source["metrics"]["object_oriented"]["classes"][0]["extension"] = {"secret": 1}
    expected = deepcopy(source["metrics"]["object_oriented"])
    expected.pop("extension")
    for row in expected["classes"]:
        row.pop("extension", None)
    view = project_metrics_view(source, profile_id="metrics.objects", profile_version=1)
    projected = view["payload"]["metrics"]
    _assert_exact_tree(projected["object_oriented"], expected)
    assert set(projected["size"]) == {"classes", "methods", "fields"}
    before = deepcopy(view)
    source["metrics"]["object_oriented"]["classes"][0]["wmc"] += 1
    assert view == before
    source_value = source["metrics"]["object_oriented"]["classes"][0]["wmc"]
    projected["object_oriented"]["classes"][0]["wmc"] += 10
    assert source["metrics"]["object_oriented"]["classes"][0]["wmc"] == source_value


def test_objects_fingerprint_ignores_omitted_sections_and_tracks_selected_values() -> None:
    source = _source()
    first = project_metrics_view(source, profile_id="metrics.objects", profile_version=1)
    source["metrics"]["activity"]["calls"] += 1
    omitted = project_metrics_view(source, profile_id="metrics.objects", profile_version=1)
    assert omitted["view_fingerprint"] == first["view_fingerprint"]
    source["metrics"]["size"]["fields"] += 1
    selected = project_metrics_view(source, profile_id="metrics.objects", profile_version=1)
    assert selected["view_fingerprint"] != first["view_fingerprint"]


@pytest.mark.parametrize("version", [True, 0, 2, "1"])
def test_objects_dispatch_has_no_version_fallback(version: object) -> None:
    with pytest.raises(ValueError):
        project_metrics_view(_source(), profile_id="metrics.objects", profile_version=version)  # type: ignore[arg-type]


def test_objects_rankings_are_exact_fixed_top_ten_and_nullable_totals_are_eligible_only() -> None:
    source = build_representative_metrics_v2("medium")
    view = project_metrics_view(source, profile_id="metrics.objects", profile_version=1)
    objects = view["payload"]["metrics"]["object_oriented"]
    descriptors = view["payload"]["truncation_metadata"]["rankings"]
    rankings = {
        "highest_weighted_method_complexity": "wmc",
        "highest_class_coupling": "cbo",
        "largest_response_sets": "rfc",
        "lowest_cohesion": "lcom",
        "deepest_inheritance": "dit",
        "most_direct_children": "noc",
    }
    assert objects["classes_analyzed"] == source["metrics"]["size"]["classes"] == len(objects["classes"])
    for name, metric in rankings.items():
        eligible = [row for row in objects["classes"] if row[metric] is not None]
        expected = sorted(eligible, key=lambda row: (-row[metric], row["class"]))[:10]
        assert objects[name] == expected
        descriptor = descriptors[f"metrics.object_oriented.{name}"]
        assert descriptor == {
            "limit": 10,
            "returned_count": min(len(eligible), 10),
            "total_matching": len(eligible),
            "truncated": len(eligible) > 10,
            "ordering": [f"{metric} descending", "class ascending"],
        }
    assert all(row["lcom"] is None for row in objects["classes"])
    assert objects["lowest_cohesion"] == []


@pytest.mark.parametrize("field", ["topology_policy", "interpretation_policy", "population_metadata", "truncation_metadata"])
def test_objects_metadata_is_exact_and_rejects_extensions(field: str) -> None:
    view = project_metrics_view(_source(), profile_id="metrics.objects", profile_version=1)
    assert view["payload"]["topology_policy"] == OBJECT_TOPOLOGY_POLICY
    assert view["payload"]["interpretation_policy"] == OBJECT_INTERPRETATION_POLICY
    view["payload"][field]["extension"] = True
    with pytest.raises(ValueError):
        validate_metrics_view_v1(view, verify_fingerprint=False)


@pytest.mark.parametrize("mutation", ["class-count", "bool-metric", "ranking", "metadata"])
def test_objects_view_rejects_inconsistent_population_types_rankings_and_metadata(mutation: str) -> None:
    view = project_metrics_view(_source(), profile_id="metrics.objects", profile_version=1)
    objects = view["payload"]["metrics"]["object_oriented"]
    if mutation == "class-count":
        objects["classes_analyzed"] += 1
    elif mutation == "bool-metric":
        objects["classes"][0]["wmc"] = True
    elif mutation == "ranking":
        objects["highest_weighted_method_complexity"] = []
    else:
        view["payload"]["interpretation_policy"]["lcom"]["zero_is_not_null"] = False
    with pytest.raises(ValueError):
        validate_metrics_view_v1(view, verify_fingerprint=False)
