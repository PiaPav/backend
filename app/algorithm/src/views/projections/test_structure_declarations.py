from copy import deepcopy

import pytest

from graph_dto import graph_fingerprint
from graph_dto.test_contract import _semantics7_graph
from metrics import calculate_graph_metrics
from views import project_graph_view


def _graph():
    graph = _semantics7_graph()
    graph["project"]["fingerprint"] = graph_fingerprint(graph)
    return graph


def test_full_projection_is_a_sorted_whitelist_and_does_not_mutate_source():
    graph = _graph()
    original = deepcopy(graph)
    view = project_graph_view(graph, profile_id="structure.declarations", profile_version=1)
    assert graph == original
    assert [node["id"] for node in view["payload"]["nodes"]] == sorted(
        node["id"] for node in graph["nodes"]
    )
    assert {edge["id"] for edge in view["payload"]["edges"]} == {
        edge["id"] for edge in graph["edges"] if edge["kind"] == "contains"
    }
    assert all(set(node) <= {"id", "kind", "qualified_name", "parent_id", "path",
                                  "class_kind", "synthetic"}
               for node in view["payload"]["nodes"])
    assert view["source"]["graph_fingerprint"] == graph["project"]["fingerprint"]


def test_projection_is_repeatable_and_ignores_collection_permutations():
    graph = _graph()
    permuted = deepcopy(graph)
    permuted["nodes"].reverse()
    permuted["edges"].reverse()
    assert project_graph_view(graph, profile_id="structure.declarations", profile_version=1) == \
        project_graph_view(permuted, profile_id="structure.declarations", profile_version=1)


def test_projected_changes_change_view_but_omitted_changes_only_change_provenance():
    graph = _graph()
    baseline = project_graph_view(graph, profile_id="structure.declarations", profile_version=1)
    changed = deepcopy(graph)
    changed["nodes"][0]["qualified_name"] += ".changed"
    changed["project"]["fingerprint"] = graph_fingerprint(changed)
    projected = project_graph_view(changed, profile_id="structure.declarations", profile_version=1)
    assert projected["payload"] != baseline["payload"]

    omitted = deepcopy(graph)
    omitted["diagnostics"].append({"id": "notice", "kind": "notice"})
    omitted["project"]["fingerprint"] = graph_fingerprint(omitted)
    result = project_graph_view(omitted, profile_id="structure.declarations", profile_version=1)
    assert result["payload"] == baseline["payload"]
    assert result["view_fingerprint"] != baseline["view_fingerprint"]


def test_source_is_validated_before_projection_and_semantics_policy_is_exact():
    graph = _graph()
    graph["nodes"][0]["path"] = "../bad.py"
    with pytest.raises(ValueError, match="Graph DTO"):
        project_graph_view(graph, profile_id="structure.declarations", profile_version=1)
    graph = _graph()
    graph["parser_semantics_version"] = 6
    graph["body"] = []
    graph["project"]["fingerprint"] = graph_fingerprint(graph)
    with pytest.raises(ValueError, match="semantics 7"):
        project_graph_view(graph, profile_id="structure.declarations", profile_version=1)


def test_invalid_source_is_reported_before_unsupported_profile_policy():
    graph = _graph()
    graph["nodes"][0]["path"] = "../bad.py"
    with pytest.raises(ValueError, match="Graph DTO"):
        project_graph_view(graph, profile_id="unsupported", profile_version=1)


@pytest.mark.parametrize("profile_id,version", [
    ("canonical.full", 1), ("structure.declarations", 2),
    ("structure.declarations", True),
])
def test_no_profile_fallback(profile_id, version):
    with pytest.raises(ValueError, match="Unsupported"):
        project_graph_view(_graph(), profile_id=profile_id, profile_version=version)


def test_empty_graph_and_metrics_rejection():
    graph = _graph()
    graph["nodes"] = []
    graph["edges"] = []
    graph["callsites"] = []
    graph["type_references"] = []
    graph["import_references"] = []
    graph["owner_structural_facts"] = []
    graph["project"]["fingerprint"] = graph_fingerprint(graph)
    view = project_graph_view(graph, profile_id="structure.declarations", profile_version=1)
    assert view["payload"] == {"nodes": [], "edges": []}
    with pytest.raises(ValueError):
        calculate_graph_metrics(view)


def test_isolated_root_projection():
    graph = _graph()
    root = next(node for node in graph["nodes"] if node["kind"] == "file")
    graph["nodes"] = [root]
    graph["edges"] = []
    graph["callsites"] = []
    graph["type_references"] = []
    graph["import_references"] = []
    graph["owner_structural_facts"] = [
        fact for fact in graph["owner_structural_facts"] if fact["owner_id"] == root["id"]
    ]
    graph["project"]["fingerprint"] = graph_fingerprint(graph)
    view = project_graph_view(graph, profile_id="structure.declarations", profile_version=1)
    assert view["payload"] == {
        "nodes": [{key: root[key] for key in ("id", "kind", "qualified_name", "parent_id", "path")}],
        "edges": [],
    }


def test_canonical_root_without_parent_id_is_materialized_with_none():
    graph = _graph()
    root = next(node for node in graph["nodes"] if node["kind"] in {"file", "module"})
    del root["parent_id"]
    graph["project"]["fingerprint"] = graph_fingerprint(graph)

    view = project_graph_view(graph, profile_id="structure.declarations", profile_version=1)

    projected_root = next(node for node in view["payload"]["nodes"] if node["id"] == root["id"])
    assert projected_root["parent_id"] is None
    assert view["source"]["graph_fingerprint"] == graph["project"]["fingerprint"]
