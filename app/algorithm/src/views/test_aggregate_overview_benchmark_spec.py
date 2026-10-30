"""Normative source/preflight specification for aggregate.overview/1."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import pytest

from graph_dto import validate_graph_v1
from views import project_graph_summary
from views.testdata import build_representative_overview_v1

MANIFEST = Path(__file__).with_name("testdata") / "aggregate_overview_benchmark_v1.json"
SIZES = {"medium": 12, "large": 24}
TARGET = {"source_basis": 100, "maximum_artifact_basis": 8}
COMPOSITION = {
    "family": "representative_overview_v1", "package_counts_including_root": SIZES,
    "roots_per_package": 2, "declarations_per_package": 6,
    "isolated_package": "last numbered package",
    "special_labels": ["<root>", "пакет"], "top_k_limit": 10,
    "collection_permutations_supported": True,
    "measurement_tuning_forbidden": True,
}
GROUPING = {
    "descriptor_version": 1,
    "path_policy": {"separator": "/", "package": "first POSIX path segment",
                    "root_package": "<root>", "root_condition": "path contains no '/'"},
    "populations": {"files": "all canonical file/module roots",
                    "edges": "unique exact non-self root pairs",
                    "packages": "labels represented by roots"},
}
TOP_K = {"limit": 10, "ties": "do not expand boundary",
         "order": "score descending then authoritative ID ascending",
         "empty_metadata": [0, 0, False]}
COMPLETENESS = {
    "kind": "one_way_projection",
    "preserves": ["source_graph_identity", "graph_native_size_and_activity_totals",
                  "file_and_package_topology_counts", "resolution_occurrence_counts",
                  "three_homogeneous_topology_rankings"],
    "omits": ["canonical_descriptors_and_locations", "individual_references_and_callsites",
              "diagnostics", "exact_edge_lists", "metrics_formulas_risk_pagerank",
              "object_metrics_averages_and_rates"],
}
WIRE = {
    "payload_keys": ["graph_kind", "wire_format", "policy_version", "totals", "statuses",
                     "file_identities", "package_identities", "rankings"],
    "totals_columns": ["directories", "files", "classes", "abstract_classes", "dataclasses",
        "functions", "methods", "synthetic_methods", "fields", "constants", "calls",
        "local_imports", "external_imports", "file_vertices", "file_edges",
        "file_cyclic_components", "package_vertices", "package_edges",
        "package_cyclic_components"],
    "status_columns": ["imports_exact", "imports_external", "imports_unresolved", "types_exact",
        "types_ambiguous", "types_external", "types_unresolved", "callsites_exact",
        "callsites_ambiguous", "callsites_external", "callsites_dynamic", "callsites_unresolved"],
    "identity_rows": {"file": ["canonical_root_id", "path"], "package": ["overview_package_id", "label"]},
    "ranking_row": ["total_matching", "returned_count", "truncated", "items"],
    "ranking_item": ["identity_index", "score"],
    "ranking_order": ["files_by_fan_in", "files_by_fan_out", "packages_by_efferent_coupling"],
}
CONTRACT = {"artifact": ["graph_summary", 1, "aggregate.overview", 1],
            "source": ["canonical_graph_dto", 1, 7], "graph_kind": "overview",
            "wire_format": 1, "policy_version": 1, "completeness": COMPLETENESS,
            "grouping": GROUPING, "top_k": TOP_K, "wire": WIRE,
            "package_id_hash_input": ["aggregate.overview", 1, "<full grouping descriptor>", "<label>"],
            "fingerprint_scope": "compact full envelope without summary_fingerprint",
            "benchmark_scope": "compact full envelope including summary_fingerprint"}


def _compact(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _package(path: str) -> str:
    return path.split("/", 1)[0] if "/" in path else "<root>"


def _package_id(label: str) -> str:
    digest = hashlib.sha256(_compact(["aggregate.overview", 1, GROUPING, label])).hexdigest()
    return f"aggregate:overview-package:{digest}"


def _scc_count(vertices: set[str], edges: set[tuple[str, str]]) -> int:
    adjacency = {vertex: [] for vertex in vertices}
    for source, target in edges:
        adjacency[source].append(target)
    index = 0
    stack: list[str] = []
    indices: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    result = 0
    def visit(vertex: str) -> None:
        nonlocal index, result
        indices[vertex] = low[vertex] = index; index += 1
        stack.append(vertex); on_stack.add(vertex)
        for target in adjacency[vertex]:
            if target not in indices:
                visit(target); low[vertex] = min(low[vertex], low[target])
            elif target in on_stack:
                low[vertex] = min(low[vertex], indices[target])
        if low[vertex] == indices[vertex]:
            component = []
            while True:
                member = stack.pop(); on_stack.remove(member); component.append(member)
                if member == vertex: break
            result += len(component) > 1
    for vertex in sorted(vertices):
        if vertex not in indices: visit(vertex)
    return result


def _model(graph: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    roots = {node["id"]: node for node in graph["nodes"] if node["parent_id"] is None}
    labels = {identifier: _package(node["path"]) for identifier, node in roots.items()}
    exact = {(ref["importer_id"], ref["target_id"]) for ref in graph["import_references"]
             if ref["resolution"] == "exact" and ref["importer_id"] != ref["target_id"]}
    package_edges = {(labels[source], labels[target]) for source, target in exact
                     if labels[source] != labels[target]}
    incoming = Counter(target for source, target in exact)
    outgoing = Counter(source for source, target in exact)
    efferent = Counter(source for source, target in package_edges)
    nodes = graph["nodes"]
    prefixes = {prefix for node in roots.values() for prefix in
                ["/".join(node["path"].split("/")[:i]) for i in range(1, len(node["path"].split("/")))]}
    facts = {fact["owner_id"]: fact for fact in graph["owner_structural_facts"]}
    activity_owners = [node for node in nodes if node["parent_id"] is None or node["kind"] == "function"
                       or (node["kind"] == "method" and node.get("synthetic") is not True)]
    calls = sum(facts[node["id"]]["call_occurrences"] for node in activity_owners)
    root_facts = [facts[identifier] for identifier in roots]
    statuses = (Counter(ref["resolution"] for ref in graph["import_references"]),
                Counter(ref["resolution"] for ref in graph["type_references"]),
                Counter(ref["resolution"] for ref in graph["callsites"]))
    totals = [len(prefixes), len(roots), sum(n["kind"] == "class" for n in nodes),
        sum(n["kind"] == "class" and n.get("class_kind") == "abstract" for n in nodes),
        sum(n["kind"] == "class" and n.get("class_kind") == "dataclass" for n in nodes),
        sum(n["kind"] == "function" for n in nodes),
        sum(n["kind"] == "method" and n.get("synthetic") is not True for n in nodes),
        sum(n["kind"] == "method" and n.get("synthetic") is True for n in nodes),
        sum(n["kind"] == "field" for n in nodes), sum(n["kind"] == "constant" for n in nodes), calls,
        sum(f["direct_import_occurrences"]["project_local"] for f in root_facts),
        sum(f["direct_import_occurrences"]["non_project"] for f in root_facts),
        len(roots), len(exact), _scc_count(set(roots), exact), len(set(labels.values())),
        len(package_edges), _scc_count(set(labels.values()), package_edges)]
    status_row = [statuses[0][s] for s in ("exact", "external", "unresolved")] + \
                 [statuses[1][s] for s in ("exact", "ambiguous", "external", "unresolved")] + \
                 [statuses[2][s] for s in ("exact", "ambiguous", "external", "dynamic", "unresolved")]
    def ranked(counter: Counter[str], ids) -> list[tuple[str, int]]:
        return sorted(((ids(key), score) for key, score in counter.items() if score > 0),
                      key=lambda row: (-row[1], row[0]))
    file_in = ranked(incoming, lambda key: key)
    file_out = ranked(outgoing, lambda key: key)
    package_out = ranked(efferent, _package_id)
    populations = {"roots": len(roots), "packages": len(set(labels.values())), "directories": len(prefixes),
                   "exact_non_self_file_pairs": len(exact), "cross_package_pairs": len(package_edges),
                   "resolution_counts": status_row, "file_sccs": totals[15], "package_sccs": totals[18],
                   "ranking_populations": [len(file_in), len(file_out), len(package_out)]}
    return {"totals": totals, "statuses": status_row, "ranked": [file_in, file_out, package_out],
            "roots": roots, "labels": labels}, populations


def _lower_bound(graph: Mapping[str, Any], model: Mapping[str, Any]) -> dict[str, Any]:
    selected_files = sorted({identifier for ranking in model["ranked"][:2] for identifier, _ in ranking[:10]})
    selected_packages = sorted({identifier for identifier, _ in model["ranked"][2][:10]})
    file_rows = [[identifier, model["roots"][identifier]["path"]] for identifier in selected_files]
    package_labels = {_package_id(label): label for label in set(model["labels"].values())}
    package_rows = [[identifier, package_labels[identifier]] for identifier in selected_packages]
    file_index = {row[0]: index for index, row in enumerate(file_rows)}
    package_index = {row[0]: index for index, row in enumerate(package_rows)}
    ranking_rows = []
    for ordinal, ranking in enumerate(model["ranked"]):
        returned = ranking[:10]; indexes = package_index if ordinal == 2 else file_index
        ranking_rows.append([len(ranking), len(returned), len(returned) < len(ranking),
                             [[indexes[identifier], score] for identifier, score in returned]])
    return {"artifact_kind": "graph_summary", "summary_schema_version": 1,
            "profile": {"id": "aggregate.overview", "version": 1},
            "source": {"graph_schema_version": 1, "parser_semantics_version": 7,
                       "graph_fingerprint": graph["project"]["fingerprint"]},
            "completeness": COMPLETENESS,
            "payload": {"graph_kind": "overview", "wire_format": 1, "policy_version": 1,
                        "totals": model["totals"], "statuses": model["statuses"],
                        "file_identities": file_rows, "package_identities": package_rows,
                        "rankings": ranking_rows},
            "summary_fingerprint": "0" * 64}


def build_manifest_candidate() -> dict[str, Any]:
    fixtures = []
    for name in ("medium", "large"):
        graph = build_representative_overview_v1(name); validate_graph_v1(graph)
        model, populations = _model(graph)
        source_raw = _compact(graph); lower = _lower_bound(graph, model); lower_raw = _compact(lower)
        runtime = project_graph_summary(graph, profile_id="aggregate.overview", profile_version=1)
        runtime_raw = _compact(runtime)
        fixtures.append({"name": name, "source": {"compact_bytes": len(source_raw),
            "full_compact_sha256": hashlib.sha256(source_raw).hexdigest(),
            "graph_fingerprint": graph["project"]["fingerprint"], "populations": populations},
            "lower_bound": {"compact_bytes": len(lower_raw),
                "full_compact_sha256": hashlib.sha256(lower_raw).hexdigest(),
                "passes_integer_gate": len(lower_raw) * 100 <= len(source_raw) * 8},
            "runtime": {"compact_bytes": len(runtime_raw),
                "full_compact_sha256": hashlib.sha256(runtime_raw).hexdigest(),
                "summary_fingerprint": runtime["summary_fingerprint"],
                "passes_integer_gate": len(runtime_raw) * 100 <= len(source_raw) * 8}})
    return {"manifest_schema_version": 1, "status": "runtime_acceptance_measured",
            "composition": COMPOSITION, "target": TARGET, "contract": CONTRACT, "fixtures": fixtures}


def test_fixture_contract_and_required_scenarios() -> None:
    for name, package_count in SIZES.items():
        graph = build_representative_overview_v1(name); validate_graph_v1(graph)
        model, populations = _model(graph)
        assert graph["schema_version"] == 1 and graph["parser_semantics_version"] == 7
        assert populations["roots"] == package_count * 2 and populations["packages"] == package_count
        assert all(count > 10 for count in populations["ranking_populations"][:2])
        assert model["ranked"][0][9][1] == model["ranked"][0][10][1]  # boundary tie
        assert model["ranked"][1][9][1] == model["ranked"][1][10][1]
        assert populations["file_sccs"] > 0 and populations["package_sccs"] > 0
        assert populations["file_sccs"] != populations["package_sccs"]
        assert model["totals"][13] > len({endpoint for edge in
            {(ref["importer_id"], ref["target_id"]) for ref in graph["import_references"]
             if ref["resolution"] == "exact" and ref["importer_id"] != ref["target_id"]}
            for endpoint in edge})
        assert model["totals"][4] > 0 and model["totals"][7] > 0
        assert all(value > 0 for value in model["statuses"])
        assert model["totals"][10] != len(graph["callsites"])
        assert model["totals"][11] + model["totals"][12] != len(graph["import_references"])
        assert any("пакет" in node["path"] for node in graph["nodes"])


def test_manifest_is_pending_or_exactly_reproducible() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["composition"] == COMPOSITION and manifest["target"] == TARGET
    assert manifest["contract"] == CONTRACT
    if manifest["status"] == "measurement_pending":
        assert manifest["fixtures"] == []
        pytest.skip("capture --print-manifest output, then replace the pending manifest")
    assert manifest == build_manifest_candidate()
    for fixture in manifest["fixtures"]:
        assert fixture["lower_bound"]["passes_integer_gate"]


def test_runtime_profile_is_exactly_registered() -> None:
    graph = build_representative_overview_v1("medium")
    summary = project_graph_summary(graph, profile_id="aggregate.overview", profile_version=1)
    model, _ = _model(graph)
    assert summary["payload"]["totals"] == model["totals"]
    assert summary["payload"]["statuses"] == model["statuses"]
    for ordinal, expected in enumerate(model["ranked"]):
        row = summary["payload"]["rankings"][ordinal]
        identities = summary["payload"]["package_identities" if ordinal == 2 else "file_identities"]
        assert [(identities[item[0]][0], item[1]) for item in row[3]] == expected[:10]
        assert row[:3] == [len(expected), min(10, len(expected)), len(expected) > 10]
    with pytest.raises(ValueError, match="Unsupported version"):
        project_graph_summary(graph, profile_id="aggregate.overview", profile_version=2)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--print-manifest", action="store_true", required=True)
    parser.parse_args()
    print(json.dumps(build_manifest_candidate(), ensure_ascii=False, sort_keys=True, indent=2))
