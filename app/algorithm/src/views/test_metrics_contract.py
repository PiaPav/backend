import json
import math
from copy import deepcopy

import pytest

from graph_dto import graph_fingerprint
from metrics import calculate_graph_metrics
from metrics.test_core import _graph
from views import (
    metrics_view_fingerprint, project_metrics_view, serialize_metrics_view,
    validate_metrics_source_v1, validate_metrics_view_v1,
)


def _source() -> dict:
    graph = _graph()
    return {"schema_version": 1, "metrics_semantics_version": 4,
            "input": {"graph_schema_version": 1, "graph_fingerprint": graph_fingerprint(graph)},
            "metrics": calculate_graph_metrics(graph)}


def test_hash_and_unicode_serialization_are_deterministic() -> None:
    source = _source(); source["extension"] = {"label": "данные"}
    view = project_metrics_view(source, profile_id="metrics.overview", profile_version=1)
    assert metrics_view_fingerprint(view) == view["view_fingerprint"]
    assert serialize_metrics_view(view) == serialize_metrics_view(deepcopy(view))
    assert serialize_metrics_view(view).endswith(b"\n")
    assert json.loads(serialize_metrics_view(view))["profile"]["id"] == "metrics.overview"


@pytest.mark.parametrize("version", [True, 0, 2])
def test_profile_versions_have_no_fallback(version: object) -> None:
    with pytest.raises(ValueError):
        project_metrics_view(_source(), profile_id="metrics.overview", profile_version=version)  # type: ignore[arg-type]


def test_source_validation_precedes_profile_selection_and_rejects_non_envelopes() -> None:
    with pytest.raises(ValueError, match="source"):
        project_metrics_view({"size": {}}, profile_id="unknown", profile_version=1)
    with pytest.raises(ValueError):
        validate_metrics_source_v1(_graph())


def test_stale_hash_and_bad_types_are_rejected() -> None:
    view = project_metrics_view(_source(), profile_id="metrics.overview", profile_version=1)
    view["payload"]["metrics"]["size"]["files"] = True
    with pytest.raises(ValueError): validate_metrics_view_v1(view)
    view = project_metrics_view(_source(), profile_id="metrics.overview", profile_version=1)
    view["payload"]["metrics"]["size"]["files"] += 1
    with pytest.raises(ValueError, match="fingerprint"): validate_metrics_view_v1(view)


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda source: source.update(schema_version=True), "version"),
        (lambda source: source["metrics"]["size"].update(files=-1), "nonnegative"),
        (lambda source: source["metrics"]["activity"].update(average_calls_per_callable=math.inf), "finite"),
        (lambda source: source["metrics"]["dependency_graph"].update(density=1.01), "rate"),
        (lambda source: source["metrics"]["dependency_graph"].update(isolated_files=["z.py", "a.py"]), "sorted"),
        (lambda source: source["metrics"]["architecture"].update(packages=list(reversed(source["metrics"]["architecture"]["packages"]))), "uniquely sorted"),
    ],
)
def test_malformed_full_sources_are_rejected_before_dispatch(mutate, match: str) -> None:
    source = _source()
    mutate(source)
    with pytest.raises(ValueError, match=match):
        project_metrics_view(source, profile_id="unknown", profile_version=1)


@pytest.mark.parametrize(
    "source",
    [
        {"size": {}},
        {"artifact_kind": "graph_view", "view_schema_version": 1},
        {"artifact_kind": "graph_summary", "summary_schema_version": 1},
        _graph(),
    ],
)
def test_raw_metrics_graph_view_and_summary_are_not_metrics_sources(source: dict) -> None:
    with pytest.raises(ValueError):
        validate_metrics_source_v1(source)


@pytest.mark.parametrize("field", ["completeness", "population_metadata", "package_grouping"])
def test_static_contract_metadata_mutation_is_rejected(field: str) -> None:
    view = project_metrics_view(_source(), profile_id="metrics.architecture", profile_version=1)
    target = view[field] if field == "completeness" else view["payload"][field]
    target["unexpected"] = True
    with pytest.raises(ValueError):
        validate_metrics_view_v1(view, verify_fingerprint=False)


def test_unknown_profile_and_strict_serializer_are_rejected() -> None:
    with pytest.raises(ValueError, match="Unsupported metrics profile"):
        project_metrics_view(_source(), profile_id="metrics.future", profile_version=1)
    view = project_metrics_view(_source(), profile_id="metrics.overview", profile_version=1)
    view["extension"] = "not allowed"
    with pytest.raises(ValueError):
        serialize_metrics_view(view)


def test_population_descriptor_separates_activity_and_call_graph_owners() -> None:
    view = project_metrics_view(_source(), profile_id="metrics.overview", profile_version=1)
    definitions = {row["id"]: row for row in view["payload"]["population_metadata"]["definitions"]}
    assert "structural call_occurrences greater than zero" in definitions["activity_call_owner"]["population"]
    assert any("including synthetic methods" in item for item in definitions["call_graph_owner"]["includes"])
    assert "call_graph_owner" in definitions["callsite"]["population"]
    binding = next(row for row in view["payload"]["population_metadata"]["metric_denominators"]
                   if row["metric"].endswith("average_calls_per_call_owner"))
    assert "activity_call_owner" in binding["denominator"]


def test_source_extensions_are_accepted_but_all_known_fields_are_required() -> None:
    source = _source()
    source["extension"] = {"future": True}
    source["metrics"]["code_quality"]["extension"] = [1]
    source["metrics"]["call_graph"]["pagerank_top"][0]["extension"] = "ok"
    validate_metrics_source_v1(source)
    del source["metrics"]["code_quality"]["average_cognitive_complexity"]
    with pytest.raises(ValueError, match="fields"):
        validate_metrics_source_v1(source)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda metrics: metrics["code_quality"].update(largest_callables={}),
        lambda metrics: metrics["object_oriented"]["classes"][0].update(lcom="bad"),
        lambda metrics: metrics["call_graph"].update(node_kinds={"method": -1}),
        lambda metrics: metrics["call_graph"].update(heaviest_edges=[{"caller": "a", "target": "b", "callsites": "1"}]),
    ],
)
def test_full_source_schema_rejects_malformed_nonprojected_metrics(mutate) -> None:
    source = _source(); mutate(source["metrics"])
    with pytest.raises(ValueError):
        validate_metrics_source_v1(source)


@pytest.mark.parametrize(
    "section,field,value",
    [
        ("dependency_graph", "cyclic_components", [["a", "a"]]),
        ("dependency_graph", "cyclic_components", [[1, 2]]),
        ("dependency_graph", "cyclic_components", [["a", "b"], ["a", "b"]]),
        ("dependency_graph", "cyclic_components", [[]]),
        ("dependency_graph", "cyclic_components", [["a"]]),
        ("architecture", "cyclic_package_components", [[]]),
        ("architecture", "cyclic_package_components", [["package"]]),
    ],
)
def test_source_and_view_reject_malformed_cyclic_components(section: str, field: str, value: object) -> None:
    source = _source(); source["metrics"][section][field] = value
    with pytest.raises(ValueError): validate_metrics_source_v1(source)
    view = project_metrics_view(_source(), profile_id="metrics.architecture", profile_version=1)
    view["payload"]["metrics"][section][field] = value
    with pytest.raises(ValueError): validate_metrics_view_v1(view, verify_fingerprint=False)


@pytest.mark.parametrize("bridge", [[["a", "a"]], [["a", "b"], ["a", "b"]], [["a", 2]], [["", "b"]]])
def test_source_and_architecture_view_reject_malformed_bridges(bridge: list) -> None:
    source = _source(); source["metrics"]["architecture"]["bridge_dependencies"] = bridge
    with pytest.raises(ValueError): validate_metrics_source_v1(source)
    view = project_metrics_view(_source(), profile_id="metrics.architecture", profile_version=1)
    view["payload"]["metrics"]["architecture"]["bridge_dependencies"] = bridge
    with pytest.raises(ValueError): validate_metrics_view_v1(view, verify_fingerprint=False)
