"""Golden benchmark for metrics.aggregate v1."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from views import project_metrics_view, validate_metrics_source_v1, validate_metrics_view_v1
from views.testdata.representative_metrics_v2 import build_representative_metrics_v2

_FIXTURES = ("medium", "large")
_MAXIMUM_VIEW_BASIS = 15
_MANIFEST = Path(__file__).with_name("testdata") / "metrics_aggregate_benchmark_v1.json"

_WHITELIST: dict[str, Any] = {
    "size": ["directories", "files", "classes", "abstract_classes", "dataclasses",
             "functions", "methods", "fields", "constants"],
    "activity": ["calls", "local_imports", "external_imports"],
    "dependency_graph": ["nodes", "edges", "weakly_connected_components"],
    "architecture": ["package_edges"],
    "code_quality": {
        "fields": ["analyzed_callables"],
        "async": ["functions"],
        "exceptions": ["raise_statements", "callables_raising"],
    },
    "object_oriented": ["classes_analyzed"],
    "call_graph": ["nodes", "edges", "callsites_in_local_edges",
                   "external_or_builtin_callsites", "unresolved_callsites",
                   "unresolved_or_external_callsites"],
}

_PATH_POPULATIONS = {
    "metrics.size.directories": {"count_kind": "entity", "population": "unique source directories"},
    "metrics.size.files": {"count_kind": "entity", "population": "canonical file/module roots"},
    "metrics.size.classes": {"count_kind": "entity", "population": "canonical classes"},
    "metrics.size.abstract_classes": {"count_kind": "entity", "population": "canonical abstract classes"},
    "metrics.size.dataclasses": {"count_kind": "entity", "population": "canonical dataclasses"},
    "metrics.size.functions": {"count_kind": "entity", "population": "non-synthetic functions"},
    "metrics.size.methods": {"count_kind": "entity", "population": "non-synthetic methods"},
    "metrics.size.fields": {"count_kind": "entity", "population": "canonical fields"},
    "metrics.size.constants": {"count_kind": "entity", "population": "canonical constants"},
    "metrics.activity.calls": {"count_kind": "occurrence", "population": "structural call occurrences of activity owners"},
    "metrics.activity.local_imports": {"count_kind": "occurrence", "population": "project-local direct import occurrences"},
    "metrics.activity.external_imports": {"count_kind": "occurrence", "population": "non-project direct import occurrences"},
    "metrics.dependency_graph.nodes": {"count_kind": "unique_topology", "population": "dependency graph roots"},
    "metrics.dependency_graph.edges": {"count_kind": "unique_topology", "population": "exact directed non-self root pairs"},
    "metrics.dependency_graph.weakly_connected_components": {"count_kind": "topology_partition", "population": "weak components of dependency roots"},
    "metrics.architecture.package_edges": {"count_kind": "unique_topology", "population": "distinct directed cross-package pairs"},
    "metrics.code_quality.analyzed_callables": {"count_kind": "entity", "population": "functions and non-synthetic methods"},
    "metrics.code_quality.async.functions": {"count_kind": "entity", "population": "async functions in analyzed callables"},
    "metrics.code_quality.exceptions.raise_statements": {"count_kind": "occurrence", "population": "raise statement occurrences"},
    "metrics.code_quality.exceptions.callables_raising": {"count_kind": "entity", "population": "analyzed callables containing raise statements"},
    "metrics.object_oriented.classes_analyzed": {"count_kind": "entity", "population": "canonical classes"},
    "metrics.call_graph.nodes": {"count_kind": "unique_topology", "population": "call-graph owners"},
    "metrics.call_graph.edges": {"count_kind": "unique_topology", "population": "exact directed canonical call-owner pairs"},
    "metrics.call_graph.callsites_in_local_edges": {"count_kind": "occurrence", "population": "local exact callsite occurrences represented by edges"},
    "metrics.call_graph.external_or_builtin_callsites": {"count_kind": "occurrence", "population": "external/builtin callsite occurrences"},
    "metrics.call_graph.unresolved_callsites": {"count_kind": "occurrence", "population": "unresolved callsite occurrences"},
    "metrics.call_graph.unresolved_or_external_callsites": {"count_kind": "occurrence", "population": "union of external/builtin and unresolved callsite occurrences"},
}

_CONTRACT = {
    "whitelist": _WHITELIST,
    "path_populations": _PATH_POPULATIONS,
    "population_metadata": {
        "descriptor_version": 1,
        "rounding_policy": {
            "kind": "decimal_places", "places": 4, "applies_to": "ratio_metrics",
        },
        "definitions": [
            {"id": "entity", "meaning": "counts of named entities or eligible entity subsets"},
            {"id": "occurrence", "meaning": "counts of occurrences; repeated facts count repeatedly"},
            {"id": "topology_partition", "meaning": "counts of components partitioning exact topology"},
            {"id": "unique_topology", "meaning": "counts of unique exact topology nodes or relations"},
        ],
        "metric_denominators": [],
    },
    "aggregate_policy": {
        "descriptor_version": 1,
        "value_policy": "exact_recursive_whitelist_copy",
        "derived_metric_values": "forbidden",
        "top_k": {"kind": "omitted", "rankings": []},
    },
}


def _compact(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


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


def build_benchmark_spec() -> dict[str, Any]:
    fixtures = []
    for name in _FIXTURES:
        source = build_representative_metrics_v2(name)
        validate_metrics_source_v1(source)
        raw = _compact(source)
        artifact = project_metrics_view(source, profile_id="metrics.aggregate", profile_version=1)
        validate_metrics_view_v1(artifact)
        artifact_raw = _compact(artifact)
        fixtures.append({
            "name": name,
            "source": {
                "metrics_schema_version": source["schema_version"],
                "metrics_semantics_version": source["metrics_semantics_version"],
                "graph_schema_version": source["input"]["graph_schema_version"],
                "graph_fingerprint": source["input"]["graph_fingerprint"],
                "compact_bytes": len(raw),
                "full_compact_sha256": hashlib.sha256(raw).hexdigest(),
                "populations": _populations(source),
            },
            "artifact": {
                "profile": {"id": "metrics.aggregate", "version": 1},
                "compact_bytes": len(artifact_raw),
                "full_compact_sha256": hashlib.sha256(artifact_raw).hexdigest(),
            },
            "target": {
                "source_basis": 100,
                "maximum_view_basis": _MAXIMUM_VIEW_BASIS,
                "maximum_compact_bytes": len(raw) * _MAXIMUM_VIEW_BASIS // 100,
            },
        })
    return {
        "manifest_schema_version": 1,
        "fixture_family": "representative_metrics_v2",
        "contract": _CONTRACT,
        "serialization": {"encoding": "utf-8", "ensure_ascii": False,
                          "sort_keys": True, "separators": [",", ":"]},
        "fixtures": fixtures,
    }


def test_manifest_equals_deterministic_golden_benchmark() -> None:
    expected = build_benchmark_spec()
    manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    assert manifest == expected
    assert build_benchmark_spec() == expected

    def flatten(node: Any, prefix: str) -> set[str]:
        if isinstance(node, list):
            return {f"{prefix}.{field}" for field in node}
        paths = set()
        for field, child in node.items():
            child_prefix = prefix if field == "fields" else f"{prefix}.{field}"
            paths.update(flatten(child, child_prefix))
        return paths

    contract = manifest["contract"]
    whitelist_paths = flatten(contract["whitelist"], "metrics")
    assert set(contract["path_populations"]) == whitelist_paths
    assert len(whitelist_paths) == 27
    assert contract["population_metadata"]["metric_denominators"] == []
    assert contract["aggregate_policy"]["top_k"]["rankings"] == []
    forbidden_field_fragments = ("top_k", "top-k", "rate", "average", "density")
    assert not any(fragment in path.lower()
                   for path in whitelist_paths for fragment in forbidden_field_fragments)

    maximums = {fixture["name"]: fixture["target"]["maximum_compact_bytes"]
                for fixture in manifest["fixtures"]}
    assert maximums == {"medium": 3575, "large": 6146}
    for fixture in manifest["fixtures"]:
        artifact = fixture["artifact"]
        assert type(artifact["compact_bytes"]) is int
        assert isinstance(artifact["full_compact_sha256"], str)
        assert len(artifact["full_compact_sha256"]) == 64
        assert artifact["compact_bytes"] * fixture["target"]["source_basis"] <= fixture["source"]["compact_bytes"] * fixture["target"]["maximum_view_basis"]


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--print-manifest", action="store_true", required=True)
    parser.parse_args()
    print(json.dumps(build_benchmark_spec(), ensure_ascii=False, sort_keys=True, indent=2))
