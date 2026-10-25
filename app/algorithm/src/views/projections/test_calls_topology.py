from copy import deepcopy

import pytest

from graph_dto import graph_fingerprint
from metrics import calculate_graph_metrics
from views import materialize_graph_profile, project_graph_view, validate_graph_view_v1
from views.testdata.representative_graph_v2 import build_representative_graph_v2


def _graph():
    graph = build_representative_graph_v2("medium")
    callables = [node for node in graph["nodes"] if node["kind"] in {"function", "method"}]
    source, target = callables[0], callables[1]
    graph["callsites"].extend([
        {"id": "call:await", "caller_id": source["id"], "expression": "await target()",
         "location": deepcopy(source["location"]), "syntactic_depth": 0, "resolution": "exact",
         "target_id": target["id"], "candidate_ids": [], "awaited": True},
        {"id": "call:module-dynamic", "caller_id": "module:benchmark.service", "expression": "dynamic()",
         "location": {"path": "benchmark/service.py", "line": 1, "column": 0},
         "syntactic_depth": 0, "resolution": "dynamic", "target_id": None,
         "candidate_ids": [], "awaited": False},
    ])
    for suffix in ("one", "two"):
        graph["callsites"].append({
            "id": f"call:pair:{suffix}", "caller_id": source["id"], "expression": "target()",
            "location": deepcopy(source["location"]), "syntactic_depth": 0, "resolution": "exact",
            "target_id": target["id"], "candidate_ids": [], "awaited": False,
        })
    for suffix, caller, called in (("self", source, source), ("reverse", target, source)):
        graph["callsites"].append({
            "id": f"call:{suffix}", "caller_id": caller["id"], "expression": "target()",
            "location": deepcopy(caller["location"]), "syntactic_depth": 0, "resolution": "exact",
            "target_id": called["id"], "candidate_ids": [], "awaited": False,
        })
    for status in ("ambiguous", "external", "dynamic", "unresolved"):
        graph["callsites"].append({
            "id": f"call:await:{status}", "caller_id": source["id"], "expression": "await target()",
            "location": deepcopy(source["location"]), "syntactic_depth": 0, "resolution": status,
            "target_id": None,
            "candidate_ids": sorted([source["id"], target["id"]]) if status == "ambiguous" else [],
            "awaited": True,
        })
    graph["edges"].extend([
        {"id": "awaits:extra", "kind": "awaits", "source_id": source["id"],
         "target_id": target["id"], "weight": 1},
        {"id": "calls:pair", "kind": "calls", "source_id": source["id"],
         "target_id": target["id"], "weight": 2},
        {"id": "calls:self", "kind": "calls", "source_id": source["id"],
         "target_id": source["id"], "weight": 1},
        {"id": "calls:reverse", "kind": "calls", "source_id": target["id"],
         "target_id": source["id"], "weight": 1},
    ])
    graph["project"]["fingerprint"] = graph_fingerprint(graph)
    return graph


def test_projector_preserves_callable_closure_topology_counts_and_input():
    graph = _graph(); original = deepcopy(graph)
    view = project_graph_view(graph, profile_id="calls.topology", profile_version=1)
    payload = view["payload"]
    assert graph == original
    assert set(payload) == {"nodes", "edges", "module_call_owner_ids", "callsite_counts"}
    assert payload["module_call_owner_ids"] == ["module:benchmark.service"]
    assert all(node["kind"] != "field" for node in payload["nodes"])
    assert all(node["kind"] != "class" or "class_kind" not in node for node in payload["nodes"])
    assert any(node.get("synthetic") is True for node in payload["nodes"])
    assert payload["callsite_counts"]["dynamic"]["non_awaited"] == 5
    assert payload["callsite_counts"]["exact"]["awaited"] == 1
    assert all(payload["callsite_counts"][status]["awaited"] == 1
               for status in ("exact", "ambiguous", "external", "dynamic", "unresolved"))
    assert any(edge["kind"] == "calls" and edge["weight"] == 2 for edge in payload["edges"])
    assert not any(edge["source_id"] == source_id and edge["kind"] in {"calls", "awaits"}
                   for source_id in payload["module_call_owner_ids"] for edge in payload["edges"])
    assert any(edge["kind"] == "awaits" for edge in payload["edges"])
    validate_graph_view_v1(view)
    assert view == materialize_graph_profile(graph, profile_id="calls.topology", profile_version=1)


def test_projection_is_deterministic_under_all_relevant_collection_permutations():
    graph = _graph(); permuted = deepcopy(graph)
    for name in ("nodes", "edges", "callsites"):
        permuted[name].reverse()
    assert project_graph_view(graph, profile_id="calls.topology", profile_version=1) == \
        project_graph_view(permuted, profile_id="calls.topology", profile_version=1)


def test_projection_preserves_exact_canonical_edges_and_full_callable_ownership_closure():
    graph = _graph()
    view = project_graph_view(graph, profile_id="calls.topology", profile_version=1)
    payload = view["payload"]

    expected_edges = sorted([
        {key: edge[key] for key in (
            ("id", "kind", "source_id", "target_id")
            if edge["kind"] == "contains"
            else ("id", "kind", "source_id", "target_id", "weight")
        )}
        for edge in graph["edges"]
        if edge["kind"] in {"calls", "awaits"}
        or (edge["kind"] == "contains"
            and edge["source_id"] in {node["id"] for node in payload["nodes"]}
            and edge["target_id"] in {node["id"] for node in payload["nodes"]})
    ], key=lambda edge: edge["id"])
    assert payload["edges"] == expected_edges

    by_id = {node["id"]: node for node in graph["nodes"]}
    expected_node_ids = {
        node["id"] for node in graph["nodes"] if node["kind"] in {"function", "method"}
    } | set(payload["module_call_owner_ids"])
    for identifier in tuple(expected_node_ids):
        while by_id[identifier].get("parent_id") is not None:
            identifier = by_id[identifier]["parent_id"]
            expected_node_ids.add(identifier)
    assert {node["id"] for node in payload["nodes"]} == expected_node_ids
    assert set(payload["module_call_owner_ids"]) != {
        node["id"] for node in payload["nodes"] if node["kind"] in {"file", "module"}
    }


def test_non_exact_callsites_only_affect_joint_counts_and_metrics_reject_view():
    graph = _graph()
    graph["callsites"] = [
        item for item in graph["callsites"]
        if item["id"].startswith("call:await:") or item["id"] == "call:module-dynamic"
    ]
    graph["edges"] = [item for item in graph["edges"] if item["kind"] not in {"calls", "awaits"}]
    graph["project"]["fingerprint"] = graph_fingerprint(graph)

    view = project_graph_view(graph, profile_id="calls.topology", profile_version=1)
    assert not any(edge["kind"] in {"calls", "awaits"} for edge in view["payload"]["edges"])
    assert view["payload"]["callsite_counts"] == {
        "exact": {"awaited": 0, "non_awaited": 0},
        "ambiguous": {"awaited": 1, "non_awaited": 0},
        "external": {"awaited": 1, "non_awaited": 0},
        "dynamic": {"awaited": 1, "non_awaited": 1},
        "unresolved": {"awaited": 1, "non_awaited": 0},
    }
    with pytest.raises(ValueError):
        calculate_graph_metrics(view)


@pytest.mark.parametrize("version", [2, True, "1"])
def test_calls_topology_has_no_version_fallback(version):
    with pytest.raises(ValueError, match="Unsupported"):
        project_graph_view(_graph(), profile_id="calls.topology", profile_version=version)


@pytest.mark.parametrize("mutation", ["weight", "count", "owners", "class"])
def test_contract_rejects_calls_topology_invariant_violations(mutation):
    view = project_graph_view(_graph(), profile_id="calls.topology", profile_version=1)
    if mutation == "weight":
        next(edge for edge in view["payload"]["edges"] if edge["kind"] in {"calls", "awaits"})["weight"] = True
    elif mutation == "count":
        view["payload"]["callsite_counts"]["exact"]["non_awaited"] += 1
    elif mutation == "owners":
        view["payload"]["module_call_owner_ids"].append("module:benchmark.service")
    else:
        method = next(node for node in view["payload"]["nodes"] if node["kind"] == "method")
        view["payload"]["edges"] = [edge for edge in view["payload"]["edges"] if edge["target_id"] != method["id"]]
    with pytest.raises(ValueError, match="Invalid Graph View DTO"):
        validate_graph_view_v1(view, verify_fingerprint=False)


def test_contract_rejects_module_call_owner_without_callsite_population():
    view = project_graph_view(_graph(), profile_id="calls.topology", profile_version=1)
    payload = view["payload"]
    payload["edges"] = [edge for edge in payload["edges"] if edge["kind"] == "contains"]
    payload["callsite_counts"] = {
        status: {"awaited": 0, "non_awaited": 0}
        for status in ("exact", "ambiguous", "external", "dynamic", "unresolved")
    }

    with pytest.raises(ValueError, match="non-exact callsite counts must cover module call owners"):
        validate_graph_view_v1(view, verify_fingerprint=False)


def test_contract_rejects_exact_function_counts_as_module_owner_population():
    view = project_graph_view(_graph(), profile_id="calls.topology", profile_version=1)
    counts = view["payload"]["callsite_counts"]
    for status in ("ambiguous", "external", "dynamic", "unresolved"):
        counts[status] = {"awaited": 0, "non_awaited": 0}

    assert sum(counts["exact"].values()) > 0
    assert any(edge["kind"] in {"calls", "awaits"}
               and edge["source_id"] not in view["payload"]["module_call_owner_ids"]
               for edge in view["payload"]["edges"])
    with pytest.raises(ValueError, match="non-exact callsite counts must cover module call owners"):
        validate_graph_view_v1(view, verify_fingerprint=False)


def test_contract_rejects_isolated_projected_root():
    view = project_graph_view(_graph(), profile_id="calls.topology", profile_version=1)
    view["payload"]["nodes"].append({
        "id": "module:isolated",
        "kind": "module",
        "qualified_name": "isolated",
        "path": "isolated.py",
    })
    view["payload"]["nodes"].sort(key=lambda node: node["id"])

    with pytest.raises(ValueError, match="every root must own a callable or be a module call owner"):
        validate_graph_view_v1(view, verify_fingerprint=False)
