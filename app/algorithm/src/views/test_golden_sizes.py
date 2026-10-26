"""Golden compact UTF-8 sizes for the graph profiles.

The command-line mode prints a candidate manifest to stdout and never writes it.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

import pytest

from graph_dto import validate_graph_v1
from views import materialize_graph_profile
from views.contract import validate_graph_view_v1
from views.summary_contract import validate_graph_summary_v1
from views.testdata import build_representative_graph_v2

_FIXTURES = ("medium", "large")
_PROFILES = (
    "inventory.minimal", "structure.declarations", "dependency.architecture", "calls.topology",
    "calls.detailed",
)
_MANIFEST = Path(__file__).with_name("testdata") / "graph_profiles_golden_v2.json"
_COMPONENT_COUNTS = {"medium": 4, "large": 10}


def _compact_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _measurement(value: Mapping[str, Any]) -> dict[str, Any]:
    compact = _compact_bytes(value)
    return {"compact_bytes": len(compact), "full_compact_sha256": hashlib.sha256(compact).hexdigest()}


def _population(graph: Mapping[str, Any]) -> dict[str, Any]:
    node_kinds = Counter(node["kind"] for node in graph["nodes"])
    edge_kinds = Counter(edge["kind"] for edge in graph["edges"])
    resolutions = {}
    for collection in ("import_references", "type_references", "callsites"):
        resolutions[collection] = dict(sorted(Counter(item["resolution"] for item in graph[collection]).items()))
    declarations = sum(count for kind, count in node_kinds.items() if kind not in {"file", "module"})
    return {
        "nodes": {"by_kind": dict(sorted(node_kinds.items())), "total": len(graph["nodes"]),
                  "roots": node_kinds["file"] + node_kinds["module"],
                  "declarations": declarations,
                  "synthetic": sum(node.get("synthetic") is True for node in graph["nodes"])},
        "edges": {"by_kind": dict(sorted(edge_kinds.items())), "total": len(graph["edges"]),
                  "contains": edge_kinds["contains"]},
        "resolutions": resolutions,
        "diagnostics": len(graph["diagnostics"]),
        "owner_structural_facts": len(graph["owner_structural_facts"]),
        "complexity_facts": sum("complexity_facts" in node for node in graph["nodes"]),
    }


def _artifact_record(artifact: Mapping[str, Any], source: Mapping[str, Any]) -> dict[str, Any]:
    profile = artifact["profile"]
    fingerprint_field = "view_fingerprint" if artifact["artifact_kind"] == "graph_view" else "summary_fingerprint"
    schema_field = "view_schema_version" if artifact["artifact_kind"] == "graph_view" else "summary_schema_version"
    if profile["id"] == "structure.declarations":
        populations = {
            "kept": {"nodes": len(artifact["payload"]["nodes"]), "contains_edges": len(artifact["payload"]["edges"])},
            "omitted": {"non_contains_edges": sum(edge["kind"] != "contains" for edge in source["edges"]),
                        "occurrence_facts": len(source["callsites"]) + len(source["import_references"]) + len(source["type_references"]),
                        "diagnostics": len(source["diagnostics"]),
                        "owner_structural_facts": len(source["owner_structural_facts"]),
                        "complexity_facts": sum("complexity_facts" in node for node in source["nodes"])}}
    elif profile["id"] == "inventory.minimal":
        populations = {
            "kept": {"root_descriptors": len(artifact["payload"]["roots"]),
                     "count_categories": len(artifact["payload"]["node_counts"])},
            "omitted": {"declaration_descriptors": sum(node["kind"] not in {"file", "module"} for node in source["nodes"]),
                        "edges": len(source["edges"]),
                        "occurrence_details": len(source["callsites"]) + len(source["import_references"]) + len(source["type_references"])}}
    elif profile["id"] == "dependency.architecture":
        populations = {
            "kept": {"nodes": len(artifact["payload"]["nodes"]),
                     "edges": len(artifact["payload"]["edges"]),
                     "import_references": len(artifact["payload"]["import_references"])},
            "omitted": {"non_class_declarations": sum(node["kind"] not in {"file", "module", "class"} for node in source["nodes"]),
                        "callsites": len(source["callsites"]),
                        "type_references": len(source["type_references"]),
                        "diagnostics": len(source["diagnostics"]),
                         "owner_structural_facts": len(source["owner_structural_facts"])}
        }
    elif profile["id"] == "calls.topology":
        payload = artifact["payload"]
        node_kinds = Counter(node["kind"] for node in payload["nodes"])
        edge_kinds = Counter(edge["kind"] for edge in payload["edges"])
        edge_weights = Counter()
        for edge in payload["edges"]:
            if edge["kind"] in {"calls", "awaits"}:
                edge_weights[edge["kind"]] += edge["weight"]
        callsite_occurrences = sum(
            count
            for status_counts in payload["callsite_counts"].values()
            for count in status_counts.values()
        )
        populations = {
            "kept": {
                "nodes": len(payload["nodes"]),
                "callable_nodes": node_kinds["function"] + node_kinds["method"],
                "ownership_context_nodes": node_kinds["file"] + node_kinds["module"] + node_kinds["class"],
                "contains_edges": edge_kinds["contains"],
                "calls_edges": edge_kinds["calls"],
                "awaits_edges": edge_kinds["awaits"],
                "calls_weight": edge_weights["calls"],
                "awaits_weight": edge_weights["awaits"],
                "module_call_owners": len(payload["module_call_owner_ids"]),
                "callsite_occurrences": callsite_occurrences,
            },
            "omitted": {
                "non_selected_nodes": len(source["nodes"]) - len(payload["nodes"]),
                "non_projected_edges": len(source["edges"]) - len(payload["edges"]),
                "callsite_details": len(source["callsites"]),
                "import_references": len(source["import_references"]),
                "type_references": len(source["type_references"]),
                "diagnostics": len(source["diagnostics"]),
                "owner_structural_facts": len(source["owner_structural_facts"]),
                "complexity_facts": sum("complexity_facts" in node for node in source["nodes"]),
            },
        }
    elif profile["id"] == "calls.detailed":
        payload = artifact["payload"]
        node_kinds = Counter(node["kind"] for node in payload["nodes"])
        edge_kinds = Counter(edge["kind"] for edge in payload["edges"])
        edge_weights = Counter()
        for edge in payload["edges"]:
            if edge["kind"] in {"calls", "awaits"}:
                edge_weights[edge["kind"]] += edge["weight"]
        populations = {
            "kept": {
                "nodes": len(payload["nodes"]),
                "callable_nodes": node_kinds["function"] + node_kinds["method"],
                "ownership_context_nodes": node_kinds["file"] + node_kinds["module"] + node_kinds["class"],
                "contains_edges": edge_kinds["contains"],
                "calls_edges": edge_kinds["calls"],
                "awaits_edges": edge_kinds["awaits"],
                "calls_weight": edge_weights["calls"],
                "awaits_weight": edge_weights["awaits"],
                "callsites": len(payload["callsites"]),
                "module_call_owners": len(payload["module_call_owner_ids"]),
                "owner_structural_facts": len(payload["owner_structural_facts"]),
                "complexity_facts": sum("complexity_facts" in node for node in payload["nodes"]),
            },
            "omitted": {
                "non_selected_nodes": len(source["nodes"]) - len(payload["nodes"]),
                "non_projected_edges": len(source["edges"]) - len(payload["edges"]),
                "import_references": len(source["import_references"]),
                "type_references": len(source["type_references"]),
                "diagnostics": len(source["diagnostics"]),
                "direct_import_occurrence_facts": sum(
                    "direct_import_occurrences" in fact for fact in source["owner_structural_facts"]
                ),
            },
        }
    else:
        raise AssertionError(f"unhandled golden profile: {profile['id']!r}")
    return {
        "profile": dict(profile), "artifact_kind": artifact["artifact_kind"],
        "artifact_schema_version": artifact[schema_field],
        "fingerprint": artifact[fingerprint_field], **_measurement(artifact), "populations": populations,
    }


def build_golden_manifest() -> dict[str, Any]:
    fixtures = []
    for name in _FIXTURES:
        source = build_representative_graph_v2(name)
        artifacts = [materialize_graph_profile(source, profile_id=profile, profile_version=1)
                     for profile in _PROFILES]
        fixtures.append({
            "name": name,
            "source": {"graph_schema_version": source["schema_version"],
                       "parser_semantics_version": source["parser_semantics_version"],
                       "graph_fingerprint": source["project"]["fingerprint"],
                       **_measurement(source), "populations": _population(source)},
            "artifacts": [_artifact_record(artifact, source) for artifact in artifacts],
            "budgets": {"inventory.minimal": None,
                        "structure.declarations": {"kind": "product_target", "source_basis": 100,
                                                    "maximum_view_basis": 45},
                        "dependency.architecture": {"kind": "product_target", "source_basis": 100,
                                                    "maximum_view_basis": 30},
                         "calls.topology": {"kind": "product_target", "source_basis": 100,
                                            "maximum_view_basis": 35},
                         "calls.detailed": {"kind": "product_target", "source_basis": 100,
                                            "maximum_view_basis": 60}},
        })
    return {
        "manifest_schema_version": 1,
        "fixture_family": "representative_graph_v2",
        "serialization": {"encoding": "utf-8", "ensure_ascii": False, "sort_keys": True,
                          "separators": [",", ":"]},
        "fixtures": fixtures,
    }


def _within_budget(view_bytes: object, source_bytes: object, maximum: object, basis: object = 100) -> bool:
    values = (view_bytes, source_bytes, maximum, basis)
    if any(type(value) is not int or value <= 0 for value in values):
        raise ValueError("budget operands must be positive non-boolean integers")
    return view_bytes * basis <= source_bytes * maximum


def _load_manifest() -> dict[str, Any]:
    return json.loads(_MANIFEST.read_text(encoding="utf-8"))


def test_golden_manifest_matches_deterministic_public_projection_results():
    expected = _load_manifest()
    actual = build_golden_manifest()
    assert expected == actual, (
        "golden manifest differs; print a reviewable candidate with "
        "python -m views.test_golden_sizes --print-manifest"
    )
    assert build_golden_manifest() == actual


def test_manifest_identity_versions_hashes_provenance_and_populations():
    manifest = _load_manifest()
    assert manifest["manifest_schema_version"] == 1
    assert manifest["fixture_family"] == "representative_graph_v2"
    assert [fixture["name"] for fixture in manifest["fixtures"]] == list(_FIXTURES)
    seen = set()
    for fixture in manifest["fixtures"]:
        assert [(artifact["profile"]["id"], artifact["profile"]["version"])
                for artifact in fixture["artifacts"]] == [
            ("inventory.minimal", 1), ("structure.declarations", 1),
            ("dependency.architecture", 1), ("calls.topology", 1),
            ("calls.detailed", 1),
        ]
        assert fixture["budgets"] == {
            "inventory.minimal": None,
            "structure.declarations": {
                "kind": "product_target", "source_basis": 100, "maximum_view_basis": 45,
            },
            "dependency.architecture": {
                "kind": "product_target", "source_basis": 100, "maximum_view_basis": 30,
            },
            "calls.topology": {
                "kind": "product_target", "source_basis": 100, "maximum_view_basis": 35,
            },
            "calls.detailed": {
                "kind": "product_target", "source_basis": 100, "maximum_view_basis": 60,
            },
        }
        source = fixture["source"]
        assert source["graph_schema_version"] == 1 and source["parser_semantics_version"] == 7
        _assert_measurement(source)
        population = source["populations"]
        assert population["nodes"]["total"] == sum(population["nodes"]["by_kind"].values())
        assert population["edges"]["total"] == sum(population["edges"]["by_kind"].values())
        assert population["edges"]["contains"] == population["edges"]["by_kind"]["contains"]
        assert set(population["nodes"]["by_kind"]) == {
            "class", "constant", "field", "file", "function", "method", "module"
        }
        assert {"contains", "imports", "calls", "field_type", "accesses_field"} <= set(population["edges"]["by_kind"])
        assert set(population["resolutions"]["import_references"]) == {"exact", "external", "unresolved"}
        assert set(population["resolutions"]["type_references"]) == {"ambiguous", "exact", "external", "unresolved"}
        assert set(population["resolutions"]["callsites"]) == {"ambiguous", "dynamic", "exact", "external", "unresolved"}
        for artifact in fixture["artifacts"]:
            key = (fixture["name"], artifact["profile"]["id"], artifact["profile"]["version"])
            assert key not in seen
            seen.add(key)
            assert artifact["profile"]["version"] == 1 and artifact["artifact_schema_version"] == 1
            assert len(artifact["fingerprint"]) == 64
            _assert_measurement(artifact)
            assert sum(artifact["populations"]["kept"].values()) > 0
            assert sum(artifact["populations"]["omitted"].values()) > 0
    medium, large = (item["source"] for item in manifest["fixtures"])
    assert large["compact_bytes"] > medium["compact_bytes"]
    assert large["populations"]["nodes"]["total"] > medium["populations"]["nodes"]["total"]
    assert large["populations"]["nodes"]["declarations"] > medium["populations"]["nodes"]["declarations"]


def _assert_measurement(record: Mapping[str, Any]) -> None:
    assert type(record["compact_bytes"]) is int and record["compact_bytes"] > 0
    digest = record["full_compact_sha256"]
    assert isinstance(digest, str) and len(digest) == 64 and all(character in "0123456789abcdef" for character in digest)


@pytest.mark.parametrize("fixture_name,n", tuple(_COMPONENT_COUNTS.items()))
def test_v2_source_population_contract_is_exact(fixture_name, n):
    graph = build_representative_graph_v2(fixture_name)
    nodes = {node["id"]: node for node in graph["nodes"]}
    node_kinds = Counter(node["kind"] for node in graph["nodes"])
    edge_kinds = Counter(edge["kind"] for edge in graph["edges"])
    assert len(nodes) == 1 + 7 * n
    assert sum(node["kind"] not in {"file", "module"} for node in nodes.values()) == 6 * n
    assert node_kinds == {"module": 1, "file": n, "class": n, "field": n,
                          "method": 2 * n, "function": n, "constant": n}
    assert node_kinds["file"] + node_kinds["module"] == n + 1
    assert sum(node.get("synthetic") is True for node in nodes.values()) == n
    assert sum("complexity_facts" in node for node in nodes.values()) == 2 * n
    assert edge_kinds == {"contains": 6 * n, "imports": n, "calls": n,
                          "field_type": n, "accesses_field": n}
    assert len(graph["edges"]) == 10 * n
    assert len(graph["owner_structural_facts"]) == 1 + 3 * n
    assert len(graph["import_references"]) == 3 * n
    assert len(graph["callsites"]) == 5 * n
    assert len(graph["type_references"]) == 4 * n
    assert len(graph["diagnostics"]) == 2 * n

    expected_statuses = {
        "import_references": {"exact", "external", "unresolved"},
        "callsites": {"exact", "ambiguous", "external", "dynamic", "unresolved"},
        "type_references": {"exact", "ambiguous", "external", "unresolved"},
    }
    for collection, statuses in expected_statuses.items():
        assert Counter(item["resolution"] for item in graph[collection]) == {
            status: n for status in statuses
        }
    assert Counter((item["kind"], item["status"]) for item in graph["diagnostics"]) == {
        ("import_resolution", "warning"): n, ("call_resolution", "info"): n,
    }


@pytest.mark.parametrize("fixture_name,n", tuple(_COMPONENT_COUNTS.items()))
def test_calls_topology_current_v2_populations_are_exact(fixture_name, n):
    source = build_representative_graph_v2(fixture_name)
    artifact = materialize_graph_profile(source, profile_id="calls.topology", profile_version=1)
    payload = artifact["payload"]
    populations = _artifact_record(artifact, source)["populations"]

    assert populations == {
        "kept": {
            "nodes": 5 * n,
            "callable_nodes": 3 * n,
            "ownership_context_nodes": 2 * n,
            "contains_edges": 4 * n,
            "calls_edges": n,
            "awaits_edges": 0,
            "calls_weight": n,
            "awaits_weight": 0,
            "module_call_owners": 0,
            "callsite_occurrences": 5 * n,
        },
        "omitted": {
            "non_selected_nodes": 1 + 2 * n,
            "non_projected_edges": 5 * n,
            "callsite_details": 5 * n,
            "import_references": 3 * n,
            "type_references": 4 * n,
            "diagnostics": 2 * n,
            "owner_structural_facts": 1 + 3 * n,
            "complexity_facts": 2 * n,
        },
    }

    counts = payload["callsite_counts"]
    assert sum(sum(row.values()) for row in counts.values()) == len(source["callsites"])
    assert counts["exact"]["non_awaited"] == populations["kept"]["calls_weight"]
    assert counts["exact"]["awaited"] == populations["kept"]["awaits_weight"]
    source_nodes = {node["id"]: node for node in source["nodes"]}
    source_root_callers = {
        callsite["caller_id"]
        for callsite in source["callsites"]
        if source_nodes[callsite["caller_id"]]["kind"] in {"file", "module"}
    }
    assert set(payload["module_call_owner_ids"]) == source_root_callers


@pytest.mark.parametrize("fixture_name,n", tuple(_COMPONENT_COUNTS.items()))
def test_calls_detailed_current_v2_populations_are_exact(fixture_name, n):
    source = build_representative_graph_v2(fixture_name)
    artifact = materialize_graph_profile(source, profile_id="calls.detailed", profile_version=1)
    payload = artifact["payload"]

    assert _artifact_record(artifact, source)["populations"] == {
        "kept": {
            "nodes": 1 + 5 * n,
            "callable_nodes": 3 * n,
            "ownership_context_nodes": 1 + 2 * n,
            "contains_edges": 4 * n,
            "calls_edges": n,
            "awaits_edges": 0,
            "calls_weight": n,
            "awaits_weight": 0,
            "callsites": 5 * n,
            "module_call_owners": 0,
            "owner_structural_facts": 1 + 3 * n,
            "complexity_facts": 2 * n,
        },
        "omitted": {
            "non_selected_nodes": 2 * n,
            "non_projected_edges": 5 * n,
            "import_references": 3 * n,
            "type_references": 4 * n,
            "diagnostics": 2 * n,
            "direct_import_occurrence_facts": 1 + n,
        },
    }
    assert Counter(item["resolution"] for item in payload["callsites"]) == {
        "exact": n, "ambiguous": n, "external": n, "dynamic": n, "unresolved": n,
    }
    exact_callsites = Counter(
        (item["caller_id"], item["target_id"])
        for item in payload["callsites"] if item["resolution"] == "exact"
    )
    calls_weights = Counter({
        (edge["source_id"], edge["target_id"]): edge["weight"]
        for edge in payload["edges"] if edge["kind"] == "calls"
    })
    assert sum(exact_callsites.values()) == n
    assert sum(calls_weights.values()) == n
    assert exact_callsites == calls_weights


@pytest.mark.parametrize("fixture_name,n", tuple(_COMPONENT_COUNTS.items()))
def test_v2_component_attribution_and_exact_relations(fixture_name, n):
    graph = build_representative_graph_v2(fixture_name)
    nodes = {node["id"]: node for node in graph["nodes"]}
    facts = {fact["owner_id"]: fact for fact in graph["owner_structural_facts"]}
    edges = graph["edges"]
    for ordinal in range(1, n + 1):
        number = f"{ordinal:02d}"
        path = f"benchmark/component_{number}.py"
        file_id = f"file:{path}"
        component_nodes = [node for node in nodes.values() if node["path"] == path]
        assert len(component_nodes) == 7
        assert all(node["location"]["path"] == path for node in component_nodes)
        owner_ids = {node["id"] for node in component_nodes
                     if node["kind"] in {"file", "function"}
                     or (node["kind"] == "method" and node.get("synthetic") is not True)}
        assert owner_ids <= facts.keys() and len(owner_ids) == 3
        assert facts[file_id]["direct_import_occurrences"] == {"project_local": 1, "non_project": 2}
        method_id = f"method:{path}:20:4:Component{number}.run"
        function_id = f"function:{path}:40:0:build_{number}"
        assert facts[file_id]["call_occurrences"] == 0
        assert facts[method_id]["call_occurrences"] == 5
        assert facts[function_id]["call_occurrences"] == 0
        assert sum(item["location"]["path"] == path for item in graph["callsites"]) == 5
        assert sum(item["location"]["path"] == path for item in graph["import_references"]) == 3
        assert sum(item["location"]["path"] == path for item in graph["type_references"]) == 4
        next_number = f"{ordinal % n + 1:02d}"
        exact_call = next(item for item in graph["callsites"]
                          if item["id"] == f"call:{number}:exact")
        assert exact_call["target_id"] == (
            f"method:benchmark/component_{next_number}.py:20:4:Component{next_number}.run"
        )
        exact_import = next(item for item in graph["import_references"]
                            if item["id"] == f"import:{number}:exact")
        assert exact_import["target_id"] == f"file:benchmark/component_{next_number}.py"
        exact_type = next(item for item in graph["type_references"]
                          if item["id"] == f"type:{number}:exact")
        assert exact_type["target_id"] == (
            f"class:benchmark/component_{next_number}.py:10:0:Component{next_number}"
        )
    module_fact = facts["module:benchmark.service"]
    assert module_fact == {"owner_id": "module:benchmark.service", "call_occurrences": 0,
                           "direct_import_occurrences": {"project_local": 0, "non_project": 0}}

    exact_calls = Counter((item["caller_id"], item["target_id"])
                          for item in graph["callsites"] if item["resolution"] == "exact")
    call_edges = Counter({(edge["source_id"], edge["target_id"]): edge["weight"]
                          for edge in edges if edge["kind"] == "calls"})
    assert exact_calls == call_edges
    exact_imports = {(item["importer_id"], item["target_id"], tuple(item["location"].items()))
                     for item in graph["import_references"] if item["resolution"] == "exact"}
    import_edges = {(edge["source_id"], edge["target_id"], tuple(edge["location"].items()))
                    for edge in edges if edge["kind"] == "imports"}
    assert exact_imports == import_edges
    exact_types = {(item["owner_id"], item["target_id"])
                   for item in graph["type_references"] if item["resolution"] == "exact"}
    type_edges = {(edge["source_id"], edge["target_id"])
                  for edge in edges if edge["kind"] == "field_type"}
    assert exact_types == type_edges


@pytest.mark.parametrize("fixture_name", _FIXTURES)
def test_structure_declarations_meets_fixture_scoped_product_target(fixture_name):
    fixture = next(item for item in _load_manifest()["fixtures"] if item["name"] == fixture_name)
    structure = next(item for item in fixture["artifacts"] if item["profile"]["id"] == "structure.declarations")
    assert _within_budget(structure["compact_bytes"], fixture["source"]["compact_bytes"], 45, 100)


@pytest.mark.parametrize("fixture_name", _FIXTURES)
def test_dependency_architecture_meets_fixture_scoped_product_target(fixture_name):
    fixture = next(item for item in _load_manifest()["fixtures"] if item["name"] == fixture_name)
    architecture = next(item for item in fixture["artifacts"] if item["profile"]["id"] == "dependency.architecture")
    assert _within_budget(architecture["compact_bytes"], fixture["source"]["compact_bytes"], 30, 100)


@pytest.mark.parametrize("fixture_name", _FIXTURES)
def test_calls_topology_meets_fixture_scoped_product_target(fixture_name):
    fixture = next(item for item in _load_manifest()["fixtures"] if item["name"] == fixture_name)
    manifest_record = next(
        item for item in fixture["artifacts"] if item["profile"]["id"] == "calls.topology"
    )
    assert _within_budget(
        manifest_record["compact_bytes"], fixture["source"]["compact_bytes"], 35, 100
    )

    source = build_representative_graph_v2(fixture_name)
    artifact = materialize_graph_profile(source, profile_id="calls.topology", profile_version=1)
    assert _within_budget(
        _measurement(artifact)["compact_bytes"], _measurement(source)["compact_bytes"], 35, 100
    )


@pytest.mark.parametrize("fixture_name", _FIXTURES)
def test_calls_detailed_meets_fixture_scoped_product_target(fixture_name):
    fixture = next(item for item in _load_manifest()["fixtures"] if item["name"] == fixture_name)
    manifest_record = next(
        item for item in fixture["artifacts"] if item["profile"]["id"] == "calls.detailed"
    )
    assert manifest_record["compact_bytes"] * 100 <= fixture["source"]["compact_bytes"] * 60

    source = build_representative_graph_v2(fixture_name)
    artifact = materialize_graph_profile(source, profile_id="calls.detailed", profile_version=1)
    assert len(_compact_bytes(artifact)) * 100 <= len(_compact_bytes(source)) * 60


def test_inventory_minimal_is_measurement_only_without_threshold():
    for fixture in _load_manifest()["fixtures"]:
        assert fixture["budgets"]["inventory.minimal"] is None
        inventory = next(item for item in fixture["artifacts"] if item["profile"]["id"] == "inventory.minimal")
        _assert_measurement(inventory)


def test_sources_and_artifacts_validate_and_preserve_provenance():
    for name in _FIXTURES:
        source = build_representative_graph_v2(name)
        validate_graph_v1(source)
        for profile in _PROFILES:
            artifact = materialize_graph_profile(source, profile_id=profile, profile_version=1)
            if artifact["artifact_kind"] == "graph_view":
                validate_graph_view_v1(artifact)
            else:
                validate_graph_summary_v1(artifact)
            assert artifact["source"]["graph_fingerprint"] == source["project"]["fingerprint"]
            assert artifact["profile"] == {"id": profile, "version": 1}
            assert artifact["completeness"]["preserves"] and artifact["completeness"]["omits"]


def test_budget_arithmetic_boundary_and_invalid_operands():
    assert _within_budget(90, 200, 45)
    assert not _within_budget(91, 200, 45)
    valid = [90, 200, 45, 100]
    for index in range(len(valid)):
        for invalid in (0, -1, True):
            values = valid.copy()
            values[index] = invalid
            with pytest.raises(ValueError, match="positive non-boolean"):
                _within_budget(*values)
    for values in ((False, 200, 45, 100), (90, False, 45, 100)):
        with pytest.raises(ValueError, match="positive non-boolean"):
            _within_budget(*values)


def test_compact_measurement_uses_utf8_full_object_and_differs_from_pretty_json():
    value = {"fingerprint": "included", "label": "Привет"}
    compact = _compact_bytes(value)
    assert len(compact) == len('{"fingerprint":"included","label":"Привет"}'.encode("utf-8"))
    assert _measurement(value)["full_compact_sha256"] == hashlib.sha256(compact).hexdigest()
    without_fingerprint = {"label": "Привет"}
    assert _measurement(value)["full_compact_sha256"] != _measurement(without_fingerprint)["full_compact_sha256"]
    pretty = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
    assert compact != pretty and len(compact) < len(pretty)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--print-manifest", action="store_true", required=True)
    parser.parse_args()
    print(json.dumps(build_golden_manifest(), ensure_ascii=False, sort_keys=True, indent=2))
