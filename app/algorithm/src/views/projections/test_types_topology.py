from copy import deepcopy

import pytest

from graph_dto import graph_fingerprint
from metrics import calculate_graph_metrics
from views import (
    graph_view_fingerprint, materialize_graph_profile, project_graph_view,
    validate_graph_view_v1,
)
from views.testdata.representative_graph_v2 import build_representative_graph_v2


def _graph():
    return build_representative_graph_v2("medium")


def _view():
    return project_graph_view(_graph(), profile_id="types.topology", profile_version=1)


def _inheritance_metrics_from_type_view(payload):
    class_ids = {node["id"] for node in payload["nodes"] if node["kind"] == "class"}
    parents = {identifier: set() for identifier in class_ids}
    children = {identifier: set() for identifier in class_ids}
    for edge in payload["edges"]:
        if edge["kind"] != "inherits":
            continue
        source, target = edge["source_id"], edge["target_id"]
        parents[source].add(target)
        if source != target:
            children[target].add(source)

    def depth(identifier, active=frozenset()):
        if identifier in active:
            return None
        parent_depths = [depth(parent, active | {identifier}) for parent in parents[identifier]]
        if any(value is None for value in parent_depths):
            return None
        return 1 + max(parent_depths) if parent_depths else 0

    return {
        identifier: {"dit": depth(identifier), "noc": len(children[identifier])}
        for identifier in class_ids
    }


def test_projection_preserves_complete_type_domain_minimal_closure_and_input():
    graph = _graph(); original = deepcopy(graph)
    view = project_graph_view(graph, profile_id="types.topology", profile_version=1)
    payload = view["payload"]
    assert graph == original
    assert set(payload) == {"nodes", "edges", "type_references"}
    assert payload["type_references"] == sorted(graph["type_references"], key=lambda item: item["id"])
    assert payload["type_references"] is not graph["type_references"]
    assert {node["id"] for node in payload["nodes"] if node["kind"] in {"class", "field"}} == {
        node["id"] for node in graph["nodes"] if node["kind"] in {"class", "field"}
    }
    assert all(set(node) == ({"id", "kind", "qualified_name", "path"}
                             if node["kind"] in {"file", "module"}
                             else {"id", "kind", "qualified_name", "parent_id", "path"})
               for node in payload["nodes"])
    assert {edge["kind"] for edge in payload["edges"]} <= {"contains", "inherits", "field_type"}
    included_roots = {node["id"] for node in payload["nodes"] if node["kind"] in {"file", "module"}}
    class_roots = {node["parent_id"] for node in payload["nodes"] if node["kind"] == "class"}
    assert included_roots == class_roots
    assert view == materialize_graph_profile(graph, profile_id="types.topology", profile_version=1)


def test_type_reference_location_in_another_valid_path_is_preserved():
    graph = _graph()
    reference = graph["type_references"][0]
    reference["location"] = {"path": "generated/type_hints.py", "line": 7, "column": 3}
    graph["project"]["fingerprint"] = graph_fingerprint(graph)

    view = project_graph_view(graph, profile_id="types.topology", profile_version=1)
    validate_graph_view_v1(view)

    projected = next(item for item in view["payload"]["type_references"]
                     if item["id"] == reference["id"])
    assert projected["location"] == reference["location"]


def test_type_reference_projection_whitelists_reference_and_location_fields():
    graph = _graph()
    reference = next(item for item in graph["type_references"]
                     if item["resolution"] == "ambiguous")
    reference["canonical_extension"] = {"mutable": []}
    reference["location"]["canonical_extension"] = {"mutable": []}
    graph["project"]["fingerprint"] = graph_fingerprint(graph)

    view = project_graph_view(graph, profile_id="types.topology", profile_version=1)
    projected = next(item for item in view["payload"]["type_references"]
                     if item["id"] == reference["id"])

    assert set(projected) == {
        "id", "owner_id", "role", "expression", "location", "resolution",
        "target_id", "candidate_ids",
    }
    assert set(projected["location"]) == {"path", "line", "column"}
    assert projected["candidate_ids"] == reference["candidate_ids"]
    assert projected["candidate_ids"] is not reference["candidate_ids"]
    validate_graph_view_v1(view)
    projected["candidate_ids"].append("independent")
    assert "independent" not in reference["candidate_ids"]


def test_non_exact_reference_omitted_optional_targets_are_materialized():
    graph = _graph()
    reference = next(item for item in graph["type_references"]
                     if item["resolution"] == "external")
    reference.pop("target_id")
    reference.pop("candidate_ids")
    graph["project"]["fingerprint"] = graph_fingerprint(graph)

    view = project_graph_view(graph, profile_id="types.topology", profile_version=1)
    projected = next(item for item in view["payload"]["type_references"]
                     if item["id"] == reference["id"])

    assert projected["target_id"] is None
    assert projected["candidate_ids"] == []
    validate_graph_view_v1(view)


def test_non_exact_references_are_preserved_without_topology_and_targets_are_nodes():
    payload = _view()["payload"]
    nodes = {node["id"] for node in payload["nodes"]}
    topology = {(edge["kind"], edge["source_id"], edge["target_id"])
                for edge in payload["edges"] if edge["kind"] in {"inherits", "field_type"}}
    exact = set()
    for reference in payload["type_references"]:
        assert set(reference["candidate_ids"]) <= nodes
        if reference["target_id"] is not None:
            assert reference["target_id"] in nodes
        if reference["resolution"] == "exact":
            exact.add(("inherits" if reference["role"] == "base" else "field_type",
                       reference["owner_id"], reference["target_id"]))
    assert topology == exact


def test_duplicate_canonical_relation_occurrences_are_not_aggregated():
    graph = _graph()
    edge = next(edge for edge in graph["edges"] if edge["kind"] == "field_type")
    duplicate = dict(edge); duplicate["id"] += ":duplicate"
    graph["edges"].append(duplicate)
    graph["project"]["fingerprint"] = graph_fingerprint(graph)
    view = project_graph_view(graph, profile_id="types.topology", profile_version=1)
    assert sum(item["kind"] == "field_type" and item["source_id"] == edge["source_id"]
               and item["target_id"] == edge["target_id"] for item in view["payload"]["edges"]) == 2


def test_projection_is_deterministic_deeply_independent_and_fingerprint_sensitive():
    graph = _graph(); permuted = deepcopy(graph)
    for name in ("nodes", "edges", "type_references"):
        permuted[name].reverse()
    first = _view(); second = project_graph_view(permuted, profile_id="types.topology", profile_version=1)
    assert first == second
    changed = deepcopy(first); changed["payload"]["type_references"][0]["expression"] += "Changed"
    assert graph_view_fingerprint(changed) != first["view_fingerprint"]
    changed["payload"]["type_references"][0]["candidate_ids"].append("changed")
    assert changed != first


@pytest.mark.parametrize("mutation", [
    "missing_relation", "spurious_relation", "dangling_candidate", "dangling_target",
    "dangling_parent", "invalid_owner", "reference_order", "duplicate_reference",
    "bad_location", "bad_payload",
])
def test_validator_rejects_malformed_type_views(mutation):
    view = _view(); payload = view["payload"]
    if mutation == "missing_relation":
        payload["edges"] = [edge for edge in payload["edges"] if edge["kind"] != "field_type"]
    elif mutation == "spurious_relation":
        relation = next(edge for edge in payload["edges"] if edge["kind"] == "field_type")
        payload["edges"].append({**relation, "id": "zz:spurious", "target_id": next(
            node["id"] for node in payload["nodes"] if node["kind"] == "class" and node["id"] != relation["target_id"])})
        payload["edges"].sort(key=lambda item: item["id"])
    elif mutation == "dangling_candidate":
        ref = next(ref for ref in payload["type_references"] if ref["resolution"] == "ambiguous"); ref["candidate_ids"][0] = "missing"
    elif mutation == "dangling_target":
        next(ref for ref in payload["type_references"] if ref["resolution"] == "exact")["target_id"] = "missing"
    elif mutation == "dangling_parent":
        next(node for node in payload["nodes"] if node["kind"] == "field")["parent_id"] = "missing"
    elif mutation == "invalid_owner":
        next(ref for ref in payload["type_references"] if ref["role"] == "field_type")["owner_id"] = next(node["id"] for node in payload["nodes"] if node["kind"] == "class")
    elif mutation == "reference_order":
        payload["type_references"].reverse()
    elif mutation == "duplicate_reference":
        payload["type_references"].append(deepcopy(payload["type_references"][0]))
    elif mutation == "bad_location":
        payload["type_references"][0]["location"]["line"] = 0
    else:
        payload["extra"] = []
    with pytest.raises(ValueError, match="Invalid Graph View DTO"):
        validate_graph_view_v1(view, verify_fingerprint=False)


def test_omitted_domains_do_not_affect_view_and_metrics_rejects_it():
    graph = _graph(); changed = deepcopy(graph)
    changed["callsites"].reverse()
    changed["owner_structural_facts"].reverse()
    for node in changed["nodes"]:
        if node["kind"] in {"method", "function"} and "complexity_facts" in node:
            node["complexity_facts"]["occurrences"].reverse()
    changed["project"]["fingerprint"] = graph["project"]["fingerprint"]
    assert project_graph_view(changed, profile_id="types.topology", profile_version=1) == _view()
    with pytest.raises(ValueError, match="Unsupported graph schema_version"):
        calculate_graph_metrics(_view())


def test_distinct_inheritance_pairs_retain_dit_noc_basis_for_cycles_self_and_multiple_inheritance():
    graph = build_representative_graph_v2("large")
    classes = [node for node in graph["nodes"] if node["kind"] == "class"]
    class_ids = [node["id"] for node in classes]
    specifications = [
        ("chain-one", classes[1], classes[0]),
        ("chain-two", classes[2], classes[1]),
        ("multiple", classes[2], classes[0]),
        ("self", classes[3], classes[3]),
        ("cycle-forward", classes[4], classes[5]),
        ("cycle-reverse", classes[5], classes[4]),
        ("cycle-descendant", classes[6], classes[4]),
        ("independent", classes[8], classes[7]),
    ]
    for suffix, owner, target in specifications:
        graph["type_references"].append({
            "id": f"type:test:{suffix}", "owner_id": owner["id"], "role": "base",
            "expression": target["qualified_name"], "location": deepcopy(owner["location"]),
            "resolution": "exact", "target_id": target["id"], "candidate_ids": [],
        })
        graph["edges"].append({
            "id": f"inherits:test:{suffix}", "kind": "inherits",
            "source_id": owner["id"], "target_id": target["id"],
        })
    graph["project"]["fingerprint"] = graph_fingerprint(graph)
    canonical_rows = {
        row["class"]: {"dit": row["dit"], "noc": row["noc"]}
        for row in calculate_graph_metrics(graph)["object_oriented"]["classes"]
    }
    payload = project_graph_view(graph, profile_id="types.topology", profile_version=1)["payload"]
    pairs = {(edge["source_id"], edge["target_id"]) for edge in payload["edges"] if edge["kind"] == "inherits"}
    assert pairs == {(owner["id"], target["id"]) for _, owner, target in specifications}
    projected_metrics = _inheritance_metrics_from_type_view(payload)
    qualified_names = {node["id"]: node["qualified_name"] for node in payload["nodes"]}
    assert {qualified_names[identifier]: values for identifier, values in projected_metrics.items()} == canonical_rows
    assert [projected_metrics[identifier] for identifier in class_ids] == [
        {"dit": 0, "noc": 2}, {"dit": 1, "noc": 1}, {"dit": 2, "noc": 0},
        {"dit": None, "noc": 0}, {"dit": None, "noc": 2},
        {"dit": None, "noc": 1}, {"dit": None, "noc": 0},
        {"dit": 0, "noc": 1}, {"dit": 1, "noc": 0}, {"dit": 0, "noc": 0},
    ]
