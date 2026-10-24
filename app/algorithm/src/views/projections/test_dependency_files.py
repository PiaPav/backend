from copy import deepcopy

import pytest

from graph_dto import graph_fingerprint
from graph_dto.test_contract import _semantics7_graph
from metrics import calculate_graph_metrics
from views import aggregate_import_edge_id, materialize_graph_profile, project_graph_view


def _graph_with_exact_references():
    graph = _semantics7_graph()
    root = next(node for node in graph["nodes"] if node["kind"] in {"file", "module"})
    location = {"path": root["path"], "line": 1, "column": 0}
    for suffix in ("one", "two"):
        identifier = f"import:{suffix}"
        graph["import_references"].append({
            "id": identifier, "importer_id": root["id"], "kind": "import",
            "module": "", "name": "self", "alias": None, "level": 0,
            "location": deepcopy(location), "resolution": "exact",
            "target_id": root["id"], "candidate_ids": [],
        })
        graph["edges"].append({
            "id": f"imports:{identifier}", "kind": "imports",
            "source_id": root["id"], "target_id": root["id"],
            "location": deepcopy(location),
        })
    graph["project"]["fingerprint"] = graph_fingerprint(graph)
    return graph, root


def test_repeated_exact_pair_is_aggregated_and_self_loop_is_preserved():
    graph, root = _graph_with_exact_references()
    original = deepcopy(graph)
    view = project_graph_view(graph, profile_id="dependency.files", profile_version=1)
    assert graph == original
    assert view["payload"]["edges"] == [{
        "id": aggregate_import_edge_id(root["id"], root["id"]), "kind": "imports",
        "source_id": root["id"], "target_id": root["id"],
        "exact_occurrence_count": 2,
    }]
    assert view["payload"]["import_resolution_counts"] == {
        "exact": 2, "external": 1, "unresolved": 0,
    }
    assert all(set(node) == {"id", "kind", "qualified_name", "path"}
               for node in view["payload"]["nodes"])


def test_projection_is_deterministic_under_source_collection_permutations():
    graph, _ = _graph_with_exact_references()
    permuted = deepcopy(graph)
    for collection in ("nodes", "edges", "import_references"):
        permuted[collection].reverse()
    assert project_graph_view(graph, profile_id="dependency.files", profile_version=1) == \
        project_graph_view(permuted, profile_id="dependency.files", profile_version=1)


def test_all_roots_reverse_pairs_and_non_exact_occurrences_are_projected_exactly():
    graph = _semantics7_graph()
    first = next(node for node in graph["nodes"] if node["kind"] == "file")
    second = {
        "id": "module:pkg", "kind": "module", "qualified_name": "pkg",
        "parent_id": None, "path": "pkg/__init__.py",
        "location": {"path": "pkg/__init__.py", "line": 1, "column": 0},
    }
    graph["nodes"].append(second)
    graph["owner_structural_facts"].append({
        "owner_id": second["id"], "call_occurrences": 0,
        "direct_import_occurrences": {"project_local": 1, "non_project": 1},
    })

    references = [
        ("forward", first, second, "exact", 0),
        ("reverse", second, first, "exact", 0),
        ("missing", second, None, "unresolved", 1),
    ]
    for suffix, importer, target, resolution, level in references:
        identifier = f"import:{suffix}"
        location = deepcopy(importer["location"])
        graph["import_references"].append({
            "id": identifier, "importer_id": importer["id"], "kind": "from",
            "module": "pkg" if level == 0 else "", "name": "item", "alias": None,
            "level": level, "location": location, "resolution": resolution,
            "target_id": None if target is None else target["id"], "candidate_ids": [],
        })
        if target is not None:
            graph["edges"].append({
                "id": f"imports:{identifier}", "kind": "imports",
                "source_id": importer["id"], "target_id": target["id"],
                "location": location,
            })
    graph["project"]["fingerprint"] = graph_fingerprint(graph)

    view = project_graph_view(graph, profile_id="dependency.files", profile_version=1)

    assert view["payload"]["nodes"] == sorted([
        {key: node[key] for key in ("id", "kind", "qualified_name", "path")}
        for node in (first, second)
    ], key=lambda node: node["id"])
    assert {(edge["source_id"], edge["target_id"], edge["exact_occurrence_count"])
            for edge in view["payload"]["edges"]} == {
        (first["id"], second["id"], 1), (second["id"], first["id"], 1),
    }
    assert view["payload"]["import_resolution_counts"] == {
        "exact": 2, "external": 1, "unresolved": 1,
    }


def test_unified_gateway_parity_non_exact_has_no_topology_and_metrics_rejects():
    graph = _semantics7_graph()
    graph["project"]["fingerprint"] = graph_fingerprint(graph)
    direct = project_graph_view(graph, profile_id="dependency.files", profile_version=1)
    assert direct == materialize_graph_profile(
        graph, profile_id="dependency.files", profile_version=1
    )
    assert direct["payload"]["edges"] == []
    assert direct["payload"]["import_resolution_counts"] == {
        "exact": 0, "external": 1, "unresolved": 0,
    }
    with pytest.raises(ValueError):
        calculate_graph_metrics(direct)


@pytest.mark.parametrize("version", [2, True, "1"])
def test_dependency_profile_has_no_version_fallback(version):
    graph = _semantics7_graph()
    graph["project"]["fingerprint"] = graph_fingerprint(graph)
    with pytest.raises(ValueError, match="Unsupported"):
        project_graph_view(graph, profile_id="dependency.files", profile_version=version)
