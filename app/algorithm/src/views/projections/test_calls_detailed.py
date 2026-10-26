from copy import deepcopy

import pytest

from graph_dto import graph_fingerprint
from metrics.logic.call_graph import calculate_call_graph_metrics
from metrics.logic.projections import MetricsGraphProjection
from views import materialize_graph_profile, project_graph_view, validate_graph_view_v1
from views.testdata.representative_graph_v2 import build_representative_graph_v2


def _graph():
    graph = build_representative_graph_v2("medium")
    graph["project"]["fingerprint"] = graph_fingerprint(graph)
    return graph


def test_projection_has_exact_payload_and_preserves_detailed_call_basis_without_mutation():
    graph = _graph(); original = deepcopy(graph)
    view = project_graph_view(graph, profile_id="calls.detailed", profile_version=1)
    payload = view["payload"]
    assert graph == original
    assert set(payload) == {"nodes", "edges", "callsites", "module_call_owner_ids", "owner_structural_facts"}
    assert {node["id"] for node in payload["nodes"] if node["kind"] in {"file", "module"}} == {
        node["id"] for node in graph["nodes"] if node["kind"] in {"file", "module"}
    }
    assert payload["callsites"] == sorted(graph["callsites"], key=lambda item: item["id"])
    assert all(set(fact) == {"owner_id", "call_occurrences"} for fact in payload["owner_structural_facts"])
    assert all("location" not in node and "class_kind" not in node for node in payload["nodes"])
    assert all("location" not in edge for edge in payload["edges"])
    validate_graph_view_v1(view)
    assert view == materialize_graph_profile(graph, profile_id="calls.detailed", profile_version=1)


def test_projection_is_deterministic_for_unordered_collections_but_preserves_control_order():
    graph = _graph(); permuted = deepcopy(graph)
    for name in ("nodes", "edges", "callsites", "owner_structural_facts"):
        permuted[name].reverse()
    permuted["project"]["fingerprint"] = graph["project"]["fingerprint"]
    assert project_graph_view(graph, profile_id="calls.detailed", profile_version=1) == project_graph_view(
        permuted, profile_id="calls.detailed", profile_version=1
    )


def test_validator_rejects_call_weight_complexity_and_owner_fact_mutations():
    view = project_graph_view(_graph(), profile_id="calls.detailed", profile_version=1)
    call_edge = next(edge for edge in view["payload"]["edges"] if edge["kind"] in {"calls", "awaits"})
    call_edge["weight"] += 1
    with pytest.raises(ValueError, match="exact callsites"):
        validate_graph_view_v1(view, verify_fingerprint=False)

    view = project_graph_view(_graph(), profile_id="calls.detailed", profile_version=1)
    callable_node = next(node for node in view["payload"]["nodes"] if "complexity_facts" in node)
    callable_node["complexity_facts"]["span"]["end"]["line"] = 0
    with pytest.raises(ValueError, match="line is invalid"):
        validate_graph_view_v1(view, verify_fingerprint=False)

    view = project_graph_view(_graph(), profile_id="calls.detailed", profile_version=1)
    view["payload"]["owner_structural_facts"][0]["direct_import_occurrences"] = {}
    with pytest.raises(ValueError, match="invalid fields"):
        validate_graph_view_v1(view, verify_fingerprint=False)


@pytest.mark.parametrize("profile_id, version", [("calls.detailed", 2), ("calls.detail", 1)])
def test_exact_api_has_no_fallback(profile_id, version):
    with pytest.raises(ValueError, match="Unsupported"):
        project_graph_view(_graph(), profile_id=profile_id, profile_version=version)


def test_projection_accepts_canonical_callsite_location_on_a_different_path():
    """Graph DTO does not require a callsite location path to equal its caller path."""
    graph = _graph()
    callsite = graph["callsites"][0]
    callsite_id = callsite["id"]
    callsite["location"]["path"] = "generated/callsite.py"
    graph["project"]["fingerprint"] = graph_fingerprint(graph)

    view = project_graph_view(graph, profile_id="calls.detailed", profile_version=1)
    projected_callsite = next(item for item in view["payload"]["callsites"] if item["id"] == callsite_id)

    assert projected_callsite["location"]["path"] == "generated/callsite.py"
    validate_graph_view_v1(view)


def test_detailed_payload_reconstructs_equivalent_metrics_call_graph_with_duplicate_root_label():
    graph = _graph()
    root = next(node for node in graph["nodes"] if node["kind"] == "module")
    duplicate = {
        **deepcopy(root),
        "id": "file:alternate/service.py",
        "kind": "file",
        "path": "alternate/service.py",
        "location": {"path": "alternate/service.py", "line": 1, "column": 0},
    }
    graph["nodes"].append(duplicate)
    graph["owner_structural_facts"].append({
        "owner_id": duplicate["id"],
        "call_occurrences": 0,
        "direct_import_occurrences": {"project_local": 0, "non_project": 0},
    })
    target = next(node for node in graph["nodes"] if node["kind"] == "function")
    graph["callsites"].append({
        "id": "call:root:exact", "caller_id": root["id"], "expression": "build()",
        "location": {"path": root["path"], "line": 2, "column": 0},
        "syntactic_depth": 0, "resolution": "exact", "target_id": target["id"],
        "candidate_ids": [], "awaited": False,
    })
    graph["edges"].append({
        "id": "calls:root:exact", "kind": "calls", "source_id": root["id"],
        "target_id": target["id"], "weight": 1,
    })
    graph["project"]["fingerprint"] = graph_fingerprint(graph)
    payload = project_graph_view(graph, profile_id="calls.detailed", profile_version=1)["payload"]
    reconstructed = {
        "parser_semantics_version": 7,
        "nodes": deepcopy(payload["nodes"]),
        "edges": deepcopy(payload["edges"]),
        "callsites": deepcopy(payload["callsites"]),
        "import_references": [],
        "owner_structural_facts": deepcopy(payload["owner_structural_facts"]),
    }

    canonical = calculate_call_graph_metrics(graph)
    projected = calculate_call_graph_metrics(
        reconstructed, projection=MetricsGraphProjection.from_graph(reconstructed)
    )

    assert projected == canonical
    assert any(item["caller"].startswith("file:benchmark/service.py") for item in canonical["heaviest_edges"])
