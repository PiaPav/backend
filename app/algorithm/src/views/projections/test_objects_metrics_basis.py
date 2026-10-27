from copy import deepcopy

import pytest

from graph_dto import graph_fingerprint
from metrics import calculate_graph_metrics
from metrics.logic.object_metrics import calculate_object_metrics
from metrics.logic.projections import MetricsGraphProjection
from views import (
    graph_view_fingerprint, materialize_graph_profile, project_graph_view,
    validate_graph_view_v1,
)
from views.projections import project_objects_metrics_basis_v1
from views.registry import profile_metadata, select_graph_profile
from views.testdata.representative_graph_v2 import build_representative_graph_v2


def _graph():
    return build_representative_graph_v2("medium")


def _view():
    return project_graph_view(_graph(), profile_id="objects.metrics_basis", profile_version=1)


def _object_metrics_from_view(view):
    basis = {"parser_semantics_version": 7, "nodes": view["payload"]["nodes"],
             "edges": view["payload"]["edges"], "callsites": [],
             "import_references": [], "owner_structural_facts": []}
    return calculate_object_metrics({}, projection=MetricsGraphProjection.from_graph(basis))


def test_projection_is_deterministic_immutable_strict_and_publicly_dispatched():
    graph = _graph(); original = deepcopy(graph); permuted = deepcopy(graph)
    for field in ("nodes", "edges", "type_references"):
        permuted[field].reverse()
    first = project_objects_metrics_basis_v1(graph)
    second = project_graph_view(permuted, profile_id="objects.metrics_basis", profile_version=1)
    assert graph == original
    assert first == second
    assert first == materialize_graph_profile(graph, profile_id="objects.metrics_basis", profile_version=1)
    assert set(first["payload"]) == {"nodes", "edges", "type_references"}
    assert first["payload"]["type_references"] == sorted(graph["type_references"], key=lambda row: row["id"])
    assert first["payload"]["type_references"] is not graph["type_references"]
    changed = deepcopy(first); changed["payload"]["nodes"][0]["qualified_name"] += ".changed"
    assert graph_view_fingerprint(changed) != first["view_fingerprint"]


def test_complete_object_populations_minimal_closure_and_synthetic_asymmetry():
    graph = _graph(); payload = _view()["payload"]
    source = {node["id"]: node for node in graph["nodes"]}; projected = {node["id"]: node for node in payload["nodes"]}
    for kind in ("class", "field", "method"):
        assert {identifier for identifier, node in projected.items() if node["kind"] == kind} == {
            identifier for identifier, node in source.items() if node["kind"] == kind}
    assert not {node["id"] for node in payload["nodes"] if node["kind"] in {"constant", "function"}}
    for node in projected.values():
        if node["kind"] == "method" and node.get("synthetic") is True:
            assert set(node) == {"id", "kind", "qualified_name", "parent_id", "path", "synthetic"}
        elif node["kind"] == "method":
            assert node["complexity_facts"] == source[node["id"]]["complexity_facts"]
            assert node["complexity_facts"] is not source[node["id"]]["complexity_facts"]
    assert all(edge["source_id"] in projected and edge["target_id"] in projected for edge in payload["edges"])
    assert not any(projected[edge["source_id"]].get("synthetic") is True
                   for edge in payload["edges"] if edge["kind"] in {"calls", "awaits", "accesses_field"})


def test_exact_boundaries_standalone_target_and_call_weights_are_metadata_only():
    graph = _graph()
    exact = next(call for call in graph["callsites"] if call["resolution"] == "exact")
    edge = next(edge for edge in graph["edges"] if edge["kind"] == "calls" and edge["source_id"] == exact["caller_id"])
    target_path = next(item["path"] for item in graph["nodes"] if item["id"] == edge["target_id"])
    function = next(node for node in graph["nodes"] if node["kind"] == "function" and node["path"] == target_path)
    edge["target_id"] = function["id"]; edge["weight"] = 7; exact["target_id"] = function["id"]
    for offset in range(6):
        duplicate = deepcopy(exact); duplicate["id"] += f":{offset}"; graph["callsites"].append(duplicate)
    graph["project"]["fingerprint"] = graph_fingerprint(graph)
    payload = project_objects_metrics_basis_v1(graph)["payload"]
    projected_function = next(node for node in payload["nodes"] if node["id"] == function["id"])
    assert set(projected_function) == {"id", "kind", "qualified_name", "parent_id", "path"}
    projected_edge = next(item for item in payload["edges"] if item["id"] == edge["id"])
    assert projected_edge["weight"] == 7
    assert len({(item["source_id"], item["target_id"]) for item in payload["edges"]
                if item["kind"] in {"calls", "awaits"}}) == len([
                    item for item in payload["edges"] if item["kind"] in {"calls", "awaits"}])
    assert all(ref["resolution"] != "exact" or ref["target_id"] is not None for ref in payload["type_references"])


def test_reconstructs_object_metrics_unweighted_including_lcom_and_inheritance_cycles():
    graph = _graph(); classes = [node for node in graph["nodes"] if node["kind"] == "class"]
    for suffix, source, target in (("self", classes[0], classes[0]),
                                   ("cycle-a", classes[1], classes[2]),
                                   ("cycle-b", classes[2], classes[1])):
        graph["type_references"].append({
            "id": f"type:test:{suffix}", "owner_id": source["id"], "role": "base",
            "expression": target["qualified_name"], "location": deepcopy(source["location"]),
            "resolution": "exact", "target_id": target["id"], "candidate_ids": [],
        })
        graph["edges"].append({"id": f"inherits:test:{suffix}", "kind": "inherits",
                               "source_id": source["id"], "target_id": target["id"]})
    graph["project"]["fingerprint"] = graph_fingerprint(graph)
    view = project_objects_metrics_basis_v1(graph)
    expected = calculate_graph_metrics(graph)["object_oriented"]
    assert _object_metrics_from_view(view) == expected
    weighted = deepcopy(view)
    for edge in weighted["payload"]["edges"]:
        if edge["kind"] in {"calls", "awaits"}: edge["weight"] *= 17
    assert _object_metrics_from_view(weighted) == expected
    assert {row["lcom"] for row in expected["classes"]} == {None}
    assert any(row["dit"] is None for row in expected["classes"])


def test_reconstruction_preserves_populated_lcom_and_standalone_rfc_semantics():
    graph = _graph()
    first_class = next(node for node in graph["nodes"] if node["kind"] == "class")
    first_method = next(node for node in graph["nodes"]
                        if node["kind"] == "method" and not node.get("synthetic")
                        and node["parent_id"] == first_class["id"])
    second_method = deepcopy(first_method)
    second_method.update(id=f"{first_method['id']}:second",
                         qualified_name=f"{first_method['qualified_name']}.second")
    graph["nodes"].append(second_method)
    graph["edges"].append({"id": f"contains:{second_method['id']}", "kind": "contains",
                           "source_id": first_class["id"], "target_id": second_method["id"]})
    graph["owner_structural_facts"].append({"owner_id": second_method["id"], "call_occurrences": 0})
    graph["project"]["fingerprint"] = graph_fingerprint(graph)
    baseline = next(item for item in calculate_graph_metrics(graph)["object_oriented"]["classes"]
                    if item["class"] == first_class["qualified_name"])

    exact = next(call for call in graph["callsites"]
                 if call["caller_id"] == first_method["id"] and call["resolution"] == "exact")
    call_edge = next(edge for edge in graph["edges"]
                     if edge["kind"] == "calls" and edge["source_id"] == first_method["id"])
    standalone = next(node for node in graph["nodes"]
                      if node["kind"] == "function" and node["path"] == first_method["path"])
    exact["target_id"] = standalone["id"]
    call_edge["target_id"] = standalone["id"]
    graph["project"]["fingerprint"] = graph_fingerprint(graph)

    expected = calculate_graph_metrics(graph)["object_oriented"]
    reconstructed = _object_metrics_from_view(project_objects_metrics_basis_v1(graph))
    row = next(item for item in expected["classes"] if item["class"] == first_class["qualified_name"])
    assert row["lcom"] == 1.0
    assert row["rfc"] == 3
    assert row["cbo"] == baseline["cbo"]
    assert reconstructed == expected


@pytest.mark.parametrize("mutation", [
    "payload", "complexity", "synthetic_source", "weight", "access_owner",
    "function_without_call", "type_support", "namespace", "order",
])
def test_standalone_validator_rejects_malformed_views(mutation):
    view = _view(); payload = view["payload"]
    if mutation == "payload": payload["extra"] = []
    elif mutation == "complexity": next(node for node in payload["nodes"] if node["kind"] == "method" and not node.get("synthetic"))["complexity_facts"].pop("span")
    elif mutation == "synthetic_source":
        edge = next(edge for edge in payload["edges"] if edge["kind"] == "calls")
        edge["source_id"] = next(node["id"] for node in payload["nodes"] if node.get("synthetic"))
    elif mutation == "weight": next(edge for edge in payload["edges"] if edge["kind"] == "calls")["weight"] = 0
    elif mutation == "access_owner":
        edge = next(edge for edge in payload["edges"] if edge["kind"] == "accesses_field")
        edge["target_id"] = next(node["id"] for node in payload["nodes"] if node["kind"] == "field" and node["parent_id"] != next(node["parent_id"] for node in payload["nodes"] if node["id"] == edge["source_id"]))
    elif mutation == "function_without_call":
        method = next(node for node in payload["nodes"] if node["kind"] == "method" and not node.get("synthetic"))
        payload["nodes"].append({**{key: method[key] for key in ("id", "kind", "qualified_name", "parent_id", "path")}, "id": "zz:function", "kind": "function"})
        payload["nodes"].sort(key=lambda row: row["id"])
    elif mutation == "type_support": payload["edges"] = [edge for edge in payload["edges"] if edge["kind"] != "field_type"]
    elif mutation == "namespace": payload["type_references"][0]["id"] = payload["nodes"][0]["id"]
    else: payload["nodes"].reverse()
    with pytest.raises(ValueError, match="Invalid Graph View DTO"):
        validate_graph_view_v1(view, verify_fingerprint=False)


def test_registry_versions_no_fallback_metrics_rejection_and_completeness():
    assert select_graph_profile("objects.metrics_basis", 1) == "graph_view"
    metadata = profile_metadata("objects.metrics_basis", 1)
    assert metadata["preserves"] == sorted(metadata["preserves"])
    assert metadata["omits"] == sorted(metadata["omits"])
    for version in (True, 0, 2, "1"):
        with pytest.raises(ValueError):
            project_graph_view(_graph(), profile_id="objects.metrics_basis", profile_version=version)
    with pytest.raises(ValueError, match="Unsupported graph schema_version"):
        calculate_graph_metrics(_view())
