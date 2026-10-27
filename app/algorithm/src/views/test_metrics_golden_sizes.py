"""Golden sizes and independent edge checks for Metrics View profiles.

CLI mode only prints a candidate manifest; it never writes project files.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

import pytest

from views import project_metrics_view, validate_metrics_source_v1, validate_metrics_view_v1
from views.testdata.representative_metrics_v2 import build_representative_metrics_v2

_FIXTURES = ("medium", "large")
_PROFILES = ("metrics.overview", "metrics.architecture", "metrics.quality", "metrics.objects")
_TARGETS = {"metrics.overview": 20, "metrics.architecture": 50, "metrics.quality": 50,
            "metrics.objects": 50}
_MANIFEST = Path(__file__).with_name("testdata") / "metrics_profiles_golden_v2.json"


def _compact(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _measurement(value: Mapping[str, Any]) -> dict[str, Any]:
    raw = _compact(value)
    return {"compact_bytes": len(raw), "full_compact_sha256": hashlib.sha256(raw).hexdigest()}


def _populations(source: Mapping[str, Any]) -> dict[str, int]:
    metrics = source["metrics"]
    return {
        "functions": metrics["size"]["functions"],
        "methods": metrics["size"]["methods"],
        "analyzed_callables": metrics["code_quality"]["analyzed_callables"],
        "dependency_nodes": metrics["dependency_graph"]["nodes"],
        "classes_analyzed": metrics["object_oriented"]["classes_analyzed"],
        "call_graph_nodes": metrics["call_graph"]["nodes"],
    }


def build_golden_manifest() -> dict[str, Any]:
    fixtures = []
    for name in _FIXTURES:
        source = build_representative_metrics_v2(name)
        artifacts = []
        for profile in _PROFILES:
            artifact = project_metrics_view(source, profile_id=profile, profile_version=1)
            artifacts.append({"profile": dict(artifact["profile"]), **_measurement(artifact)})
        fixtures.append({
            "name": name,
            "source": {
                "metrics_schema_version": source["schema_version"],
                "metrics_semantics_version": source["metrics_semantics_version"],
                "graph_schema_version": source["input"]["graph_schema_version"],
                "graph_fingerprint": source["input"]["graph_fingerprint"],
                **_measurement(source),
                "populations": _populations(source),
            },
            "artifacts": artifacts,
            "targets": {profile: {"source_basis": 100, "maximum_view_basis": limit}
                        for profile, limit in _TARGETS.items()},
        })
    return {
        "manifest_schema_version": 1,
        "fixture_family": "representative_metrics_v2",
        "serialization": {"encoding": "utf-8", "ensure_ascii": False,
                          "sort_keys": True, "separators": [",", ":"]},
        "fixtures": fixtures,
    }


def _load_manifest() -> dict[str, Any]:
    return json.loads(_MANIFEST.read_text(encoding="utf-8"))


def _quality(population: int) -> dict[str, Any]:
    largest = [{"node": f"node-{index:02d}", "lines": 5}
               for index in range(min(population, 10))]
    return {
        "analyzed_callables": population,
        "average_cyclomatic_complexity": 0.0,
        "average_cognitive_complexity": 0.0,
        "average_lines_per_callable": 0.0,
        "maximum_control_nesting": 0,
        "high_complexity_callables": [], "largest_callables": largest,
        "deeply_nested_callables": [],
        "async": {"functions": 0, "without_await": []},
        "exceptions": {"raise_statements": 0, "callables_raising": 0,
                       "raised_types": {}, "caught_types": {}, "broad_handlers": []},
    }


def _source_with_population(population: int) -> dict[str, Any]:
    source = build_representative_metrics_v2("medium")
    source["metrics"]["size"]["functions"] = population
    source["metrics"]["size"]["methods"] = 0
    source["metrics"]["code_quality"] = _quality(population)
    return source


def test_manifest_equals_deterministic_public_results() -> None:
    actual = build_golden_manifest()
    assert _load_manifest() == actual
    assert build_golden_manifest() == actual


def test_full_sources_artifacts_provenance_and_exact_populations() -> None:
    expected_components = {"medium": 20, "large": 50}
    for name in _FIXTURES:
        source = build_representative_metrics_v2(name)
        validate_metrics_source_v1(source)
        population = _populations(source)
        assert population["analyzed_callables"] == population["functions"] + population["methods"]
        count = expected_components[name]
        assert population == {
            "functions": count, "methods": count, "analyzed_callables": count * 2,
            "dependency_nodes": count + 1, "classes_analyzed": count,
            "call_graph_nodes": count * 3,
        }
        for profile in _PROFILES:
            artifact = project_metrics_view(source, profile_id=profile, profile_version=1)
            validate_metrics_view_v1(artifact)
            assert artifact["source"] == {
                "metrics_schema_version": 1, "metrics_semantics_version": 4,
                "graph_schema_version": 1,
                "graph_fingerprint": source["input"]["graph_fingerprint"],
            }


@pytest.mark.parametrize("population", [0, 1, 9, 10, 11])
def test_quality_truncation_boundaries_and_fixed_size_ties(population: int) -> None:
    view = project_metrics_view(_source_with_population(population), profile_id="metrics.quality", profile_version=1)
    rows = view["payload"]["metrics"]["code_quality"]["largest_callables"]
    descriptor = view["payload"]["truncation_metadata"]["rankings"]["metrics.code_quality.largest_callables"]
    assert [row["node"] for row in rows] == [f"node-{index:02d}" for index in range(min(population, 10))]
    assert descriptor == {"limit": 10, "returned_count": min(population, 10),
                          "total_matching": population, "truncated": population > 10,
                          "ordering": ["lines descending", "node ascending"]}


@pytest.mark.parametrize("cyclomatic,cognitive,accepted", [(9, 14, False), (10, 14, True), (9, 15, True)])
def test_quality_threshold_exact_boundaries(cyclomatic: int, cognitive: int, accepted: bool) -> None:
    source = _source_with_population(1)
    source["metrics"]["code_quality"]["high_complexity_callables"] = [{
        "node": "boundary", "cyclomatic": cyclomatic, "cognitive": cognitive,
        "lines": 1, "nesting": 0,
    }]
    if accepted:
        validate_metrics_source_v1(source)
    else:
        with pytest.raises(ValueError, match="threshold"):
            validate_metrics_source_v1(source)


@pytest.mark.parametrize("nesting,accepted", [(3, False), (4, True)])
def test_deep_nesting_exact_boundary(nesting: int, accepted: bool) -> None:
    source = _source_with_population(1)
    source["metrics"]["code_quality"]["maximum_control_nesting"] = nesting
    source["metrics"]["code_quality"]["deeply_nested_callables"] = [{"node": "boundary", "nesting": nesting}]
    if accepted:
        validate_metrics_source_v1(source)
    else:
        with pytest.raises(ValueError, match="threshold"):
            validate_metrics_source_v1(source)


@pytest.mark.parametrize("mutation", ["population", "metadata", "zero-lines", "zero-cyclomatic"])
def test_quality_rejects_population_metadata_and_impossible_values(mutation: str) -> None:
    source = _source_with_population(1)
    if mutation == "population":
        source["metrics"]["code_quality"]["analyzed_callables"] = 2
        with pytest.raises(ValueError, match="does not match"):
            validate_metrics_source_v1(source)
        return
    if mutation in {"zero-lines", "zero-cyclomatic"}:
        row = {"node": "bad", "cyclomatic": 10, "cognitive": 0, "lines": 1, "nesting": 0}
        row["lines" if mutation == "zero-lines" else "cyclomatic"] = 0
        source["metrics"]["code_quality"]["high_complexity_callables"] = [row]
        with pytest.raises(ValueError, match="impossible"):
            validate_metrics_source_v1(source)
        return
    view = project_metrics_view(source, profile_id="metrics.quality", profile_version=1)
    view["payload"]["threshold_policy"]["high_complexity"]["cyclomatic_gte"] = 9
    with pytest.raises(ValueError, match="threshold_policy"):
        validate_metrics_view_v1(view, verify_fingerprint=False)


@pytest.mark.parametrize("fixture_name", _FIXTURES)
@pytest.mark.parametrize("profile", _PROFILES)
def test_fixture_scoped_targets_use_integer_arithmetic(fixture_name: str, profile: str) -> None:
    fixture = next(item for item in _load_manifest()["fixtures"] if item["name"] == fixture_name)
    artifact = next(item for item in fixture["artifacts"] if item["profile"]["id"] == profile)
    limit = _TARGETS[profile]
    assert artifact["compact_bytes"] * 100 <= fixture["source"]["compact_bytes"] * limit


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--print-manifest", action="store_true", required=True)
    parser.parse_args()
    print(json.dumps(build_golden_manifest(), ensure_ascii=False, sort_keys=True, indent=2))
