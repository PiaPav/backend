"""Frozen source-side rejection gate for aggregate.packages v1."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from graph_dto import validate_graph_v1
from views.testdata import build_representative_packages_v1

FIXTURE_COMPOSITION = {"family": "representative_packages_v1", "package_counts": {"medium": 4, "large": 10},
                       "additional_root_package": "<root>", "files_per_package": 3,
                       "isolated_package": "last numbered package"}
TARGET = {"source_basis": 100, "maximum_artifact_basis": 15}
PAYLOAD_FIELDS = ["graph_kind", "package_grouping", "nodes", "edges"]
NODE_FIELDS = ["id", "package", "file_count", "declaration_count", "class_count",
               "abstract_class_count", "import_occurrence_counts", "internal_imports"]
EDGE_FIELDS = ["id", "kind", "source_id", "target_id", "unique_file_pair_count",
               "canonical_import_edge_count", "exact_import_occurrence_count"]
NESTED_NODE_FIELDS = {
    "import_occurrence_counts": ["exact", "external", "unresolved"],
    "internal_imports": ["unique_file_pair_count", "canonical_import_edge_count",
                         "exact_import_occurrence_count", "self_import_occurrence_count"],
}
COMPLETENESS = {
    "kind": "one_way_projection",
    "preserves": [
        "package_declaration_population_counts", "package_file_and_class_population_counts",
        "package_import_resolution_occurrence_counts", "package_internal_import_population_counts",
        "package_quotient_exact_import_topology", "package_quotient_weight_populations",
        "source_graph_identity",
    ],
    "omits": [
        "call_relations", "callable_complexity_facts", "callsites",
        "canonical_declaration_descriptors", "canonical_file_descriptors",
        "canonical_import_edge_ids", "diagnostics", "import_occurrence_details",
        "intra_package_import_topology", "node_and_edge_locations", "owner_structural_facts",
        "type_references_and_relations",
    ],
}
COUNT_INVARIANTS = [
    "file_count_positive",
    "abstract_class_count<=class_count<=declaration_count",
    "self_import_occurrence_count<=exact_import_occurrence_count",
    "unique_file_pair_count<=canonical_import_edge_count==exact_import_occurrence_count",
    "package_self_edges_omitted",
    "ordered_package_endpoint_pair_unique",
    "global_exact_references=cross_edge_exact_occurrences+internal_exact_occurrences",
    "global_canonical_import_edges=cross_edge_canonical_import_edges+internal_canonical_import_edges",
    "global_distinct_exact_file_pairs=cross_edge_unique_file_pairs+internal_unique_file_pairs",
]
PACKAGE_GROUPING = {
    "descriptor_version": 1,
    "path_policy": {"separator": "/", "package": "first POSIX path segment", "root_package": "<root>",
                    "root_condition": "path contains no '/'"},
    "populations": {
        "files": "all canonical file/module roots",
        "declarations": "all canonical non-root nodes attributed through their owning root; synthetic methods included",
        "classes": "canonical classes directly owned by roots",
        "abstract_classes": "direct-root-owned classes with class_kind abstract",
        "import_occurrences": "all canonical import references attributed by importer root package",
    },
    "quotient_edges": {"direction": "dependent package to dependency package",
                       "source_relation": "exact canonical root imports", "self_edges": "omitted",
                       "non_exact_relations": "do not create edges"},
}
ID_HASH_INPUT_POLICY = {
    "serialization": {"encoding": "utf-8", "ensure_ascii": False, "sort_keys": True,
                      "separators": [",", ":"]},
    "package_id": {"prefix": "aggregate:package:",
                   "input": ["aggregate.packages", 1, "<full package_grouping descriptor>", "<package>"]},
    "edge_id": {"prefix": "aggregate:package-imports:",
                "input": ["aggregate.packages", 1, "<source_package_id>", "<target_package_id>"]},
}
CONTRACT = {"artifact_identity": {"artifact_kind": "graph_summary", "summary_schema_version": 1},
            "profile": {"id": "aggregate.packages", "version": 1}, "graph_kind": "quotient",
            "source_requirements": {"graph_schema_version": 1, "parser_semantics_version": 7},
            "completeness": COMPLETENESS, "payload_fields": PAYLOAD_FIELDS,
            "node_fields": NODE_FIELDS, "nested_node_fields": NESTED_NODE_FIELDS,
            "edge_fields": EDGE_FIELDS, "count_invariants": COUNT_INVARIANTS,
            "package_grouping": PACKAGE_GROUPING, "id_hash_input_policy": ID_HASH_INPUT_POLICY,
            "canonical_ordering": {"nodes": "id", "edges": "id"},
            "artifact_serialization": {
                "encoding": "utf-8", "ensure_ascii": False, "sort_keys": True,
                "separators": [",", ":"], "fingerprint_algorithm": "sha256",
                "fingerprint_scope": "full envelope without summary_fingerprint",
                "benchmark_scope": "full compact artifact including summary_fingerprint",
            },
            "artifact_status": "rejected_size_target"}
EXPECTED_POPULATIONS = {
    "medium": {"package_count": 5, "package_labels": ["<root>", "pkg01", "pkg02", "pkg03", "pkg04"],
               "roots": 15, "declarations": 25, "classes": 10, "abstract_classes": 5,
               "synthetic_methods": 5, "import_status_counts": {"exact": 26, "external": 5, "unresolved": 5},
               "distinct_exact_file_pairs": 22, "canonical_import_edges": 26,
               "exact_self_occurrences": 5, "exact_internal_occurrences": 10,
               "exact_cross_occurrences": 16, "distinct_cross_package_pairs": 8,
               "quotient_cycle_without_file_scc": True},
    "large": {"package_count": 11,
              "package_labels": ["<root>"] + [f"pkg{i:02d}" for i in range(1, 11)],
              "roots": 33, "declarations": 55, "classes": 22, "abstract_classes": 11,
              "synthetic_methods": 11, "import_status_counts": {"exact": 62, "external": 11, "unresolved": 11},
              "distinct_exact_file_pairs": 52, "canonical_import_edges": 62,
              "exact_self_occurrences": 11, "exact_internal_occurrences": 22,
              "exact_cross_occurrences": 40, "distinct_cross_package_pairs": 20,
              "quotient_cycle_without_file_scc": True},
}
FROZEN_SOURCE_MEASUREMENTS = {
    "medium": {"graph_schema_version": 1, "parser_semantics_version": 7,
               "graph_fingerprint": "73626caa76d937db2af3422b67c7f5cbea74d5e239e743592aecca0d40def059",
               "compact_bytes": 31100,
               "full_compact_sha256": "aae07aa624f55ef530b4fb8e8be27a3323f4d1d92291a2155c67a3bdb17fa0ff"},
    "large": {"graph_schema_version": 1, "parser_semantics_version": 7,
              "graph_fingerprint": "414dd2e5aa9df7ed2ff51fb318ed7b8ca01f92882a286f9210d834cc6bdde79c",
              "compact_bytes": 71256,
              "full_compact_sha256": "cb07ab3676e2f10218dd67ccaf0679655391ced987ead7ca6219e67ce7bda333"},
}
REJECTED_ARTIFACT_MEASUREMENTS = {
    "medium": {
        "compact_bytes": 7054,
        "full_compact_sha256": "ab26f30ef0876fb76d7c66bb0e4ae96e2ee5d6f93a458ea4e0df301f9744d7fa",
        "summary_fingerprint": "dfd89948f25ddbb277275d01a9db7e4dcfe10619abac9a3c380da2c6b8a5fb8b",
        "populations": {"package_count": 5, "quotient_edge_count": 8, "file_count": 15,
                        "declaration_count": 25, "class_count": 10, "abstract_class_count": 5,
                        "exact_import_occurrence_count": 26},
        "size_cap_bytes": 4665,
        "contract_lower_bound_bytes": 5246,
    },
    "large": {
        "compact_bytes": 14314,
        "full_compact_sha256": "1f4941671fd0f3f55dc08f7f18b1dfbb572ce2144cd2a04732cb492f2718544d",
        "summary_fingerprint": "a604bea360357facfeb4f1cd7cfc4794b1b0e3afd3895239716f12e2004e5337",
        "populations": {"package_count": 11, "quotient_edge_count": 20, "file_count": 33,
                        "declaration_count": 55, "class_count": 22, "abstract_class_count": 11,
                        "exact_import_occurrence_count": 62},
        "size_cap_bytes": 10688,
        "contract_lower_bound_bytes": 12512,
    },
}
_MANIFEST = Path(__file__).with_name("testdata") / "aggregate_packages_benchmark_v1.json"


def _package(path: str) -> str:
    return path.split("/", 1)[0] if "/" in path else "<root>"


def _has_nontrivial_cycle(vertices: set[str], edges: set[tuple[str, str]]) -> bool:
    adjacency = {vertex: [] for vertex in vertices}
    for source, target in edges:
        if source != target:
            adjacency[source].append(target)
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(vertex: str) -> bool:
        if vertex in visiting:
            return True
        if vertex in visited:
            return False
        visiting.add(vertex)
        if any(visit(target) for target in adjacency[vertex]):
            return True
        visiting.remove(vertex)
        visited.add(vertex)
        return False

    return any(visit(vertex) for vertex in vertices)


def _populations(graph: Mapping[str, Any]) -> dict[str, Any]:
    roots = {node["id"]: node for node in graph["nodes"] if node["parent_id"] is None}
    root_packages = {node_id: _package(node["path"]) for node_id, node in roots.items()}
    references = graph["import_references"]
    exact = [reference for reference in references if reference["resolution"] == "exact"]
    exact_pairs = {(reference["importer_id"], reference["target_id"]) for reference in exact}
    cross = [reference for reference in exact
             if root_packages[reference["importer_id"]] != root_packages[reference["target_id"]]]
    internal = [reference for reference in exact if reference not in cross]
    package_pairs = {(root_packages[reference["importer_id"]], root_packages[reference["target_id"]])
                     for reference in cross}
    file_edges = {(reference["importer_id"], reference["target_id"]) for reference in exact}
    canonical_import_edges = [edge for edge in graph["edges"] if edge["kind"] == "imports"]
    return {
        "package_count": len(set(root_packages.values())),
        "package_labels": sorted(set(root_packages.values())),
        "roots": len(roots),
        "declarations": len(graph["nodes"]) - len(roots),
        "classes": sum(node["kind"] == "class" for node in graph["nodes"]),
        "abstract_classes": sum(node["kind"] == "class" and node.get("class_kind") == "abstract"
                                for node in graph["nodes"]),
        "synthetic_methods": sum(node["kind"] == "method" and node.get("synthetic") is True
                                 for node in graph["nodes"]),
        "import_status_counts": dict(sorted(Counter(reference["resolution"] for reference in references).items())),
        "distinct_exact_file_pairs": len(exact_pairs),
        "canonical_import_edges": len(canonical_import_edges),
        "exact_self_occurrences": sum(reference["importer_id"] == reference["target_id"] for reference in internal),
        "exact_internal_occurrences": len(internal),
        "exact_cross_occurrences": len(cross),
        "distinct_cross_package_pairs": len(package_pairs),
        "quotient_cycle_without_file_scc": (
            _has_nontrivial_cycle(set(root_packages.values()), package_pairs)
            and not _has_nontrivial_cycle(set(roots), file_edges)
        ),
    }


def _compact(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def build_source_manifest_candidate() -> dict[str, Any]:
    fixtures = []
    for name in ("medium", "large"):
        graph = build_representative_packages_v1(name)
        validate_graph_v1(graph)
        raw = _compact(graph)
        populations = _populations(graph)
        assert populations == EXPECTED_POPULATIONS[name]
        fixtures.append({"name": name, "source": {"graph_schema_version": 1, "parser_semantics_version": 7,
                         "graph_fingerprint": graph["project"]["fingerprint"], "compact_bytes": len(raw),
                         "full_compact_sha256": hashlib.sha256(raw).hexdigest(), "populations": populations}})
    return {"manifest_schema_version": 1, "status": "source_measured", "composition": FIXTURE_COMPOSITION,
            "target": TARGET, "contract": CONTRACT, "fixtures": fixtures}


def build_rejection_spec() -> dict[str, Any]:
    candidate = build_source_manifest_candidate()
    candidate["status"] = "runtime_rejected_size_target"
    candidate["contract"] = dict(candidate["contract"], artifact_status="rejected_size_target")
    for fixture in candidate["fixtures"]:
        fixture["rejected_artifact"] = REJECTED_ARTIFACT_MEASUREMENTS[fixture["name"]]
    return candidate


def test_fixed_contract_and_fixture_composition() -> None:
    manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    assert manifest["composition"] == FIXTURE_COMPOSITION
    assert manifest["target"] == TARGET
    assert manifest["contract"] == CONTRACT
    assert manifest["contract"]["nested_node_fields"] == NESTED_NODE_FIELDS
    assert manifest["contract"]["completeness"] == COMPLETENESS
    assert manifest["status"] == "runtime_rejected_size_target"
    frozen_sources = {fixture["name"]: fixture["source"] for fixture in manifest["fixtures"]}
    for name in ("medium", "large"):
        graph = build_representative_packages_v1(name)
        validate_graph_v1(graph)
        assert _populations(graph) == EXPECTED_POPULATIONS[name]
        source = frozen_sources[name]
        assert source["graph_schema_version"] == 1
        assert source["parser_semantics_version"] == 7
        assert source["populations"] == EXPECTED_POPULATIONS[name]
        assert {key: value for key, value in source.items() if key != "populations"} == \
            FROZEN_SOURCE_MEASUREMENTS[name]


def test_source_measurements_are_frozen() -> None:
    manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    assert manifest["status"] != "source_measurement_pending", (
        "source measurement pending; run this module with --print-manifest and replace only status/fixtures"
    )
    candidate = build_source_manifest_candidate()
    assert manifest["composition"] == candidate["composition"]
    assert manifest["target"] == candidate["target"]
    for actual, expected in zip(manifest["fixtures"], candidate["fixtures"]):
        assert actual["name"] == expected["name"]
        assert actual["source"] == expected["source"]


def test_rejected_runtime_measurements_are_frozen() -> None:
    manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    assert manifest == build_rejection_spec()
    for fixture in manifest["fixtures"]:
        rejected = fixture["rejected_artifact"]
        assert rejected["contract_lower_bound_bytes"] > rejected["size_cap_bytes"]
        assert rejected["compact_bytes"] >= rejected["contract_lower_bound_bytes"]
        assert rejected["compact_bytes"] > rejected["size_cap_bytes"]


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--print-manifest", action="store_true", required=True)
    parser.parse_args()
    print(json.dumps(build_rejection_spec(), ensure_ascii=False, sort_keys=True, indent=2))
