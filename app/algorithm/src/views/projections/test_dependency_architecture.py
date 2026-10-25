from copy import deepcopy
import ast
from pathlib import Path

import pytest

from graph_dto import graph_fingerprint
from graph_dto.test_contract import _semantics7_graph
from metrics import calculate_graph_metrics
from views import aggregate_import_edge_id, materialize_graph_profile, project_graph_view
from views.metrics_contract import PACKAGE_GROUPING


def _graph():
    graph = _semantics7_graph()
    graph["compatible_extension"] = {"ignored": True}
    graph["project"]["fingerprint"] = graph_fingerprint(graph)
    return graph


def test_projection_preserves_whitelisted_roots_classes_ownership_and_references():
    graph = _graph(); original = deepcopy(graph)
    view = project_graph_view(graph, profile_id="dependency.architecture", profile_version=1)
    assert graph == original
    assert view == materialize_graph_profile(graph, profile_id="dependency.architecture", profile_version=1)
    assert view["payload"]["package_grouping"] == PACKAGE_GROUPING
    assert view["payload"]["import_references"] == sorted(graph["import_references"], key=lambda row: row["id"])
    assert all(set(node) == ({"id", "kind", "qualified_name", "path", "parent_id", "class_kind"} if node["kind"] == "class" else {"id", "kind", "qualified_name", "path"}) for node in view["payload"]["nodes"])
    assert all(set(edge) == {"id", "kind", "source_id", "target_id"} for edge in view["payload"]["edges"] if edge["kind"] == "contains")
    view["payload"]["import_references"][0]["location"]["line"] += 1
    assert graph == original


def test_repeated_reverse_and_self_exact_occurrences_are_separate_from_aggregate_edges():
    graph = _graph(); roots = [node for node in graph["nodes"] if node["kind"] in {"file", "module"}]
    if len(roots) == 1:
        second = deepcopy(roots[0]); second.update({"id": "file:second.py", "qualified_name": "second", "path": "second.py", "location": {"path": "second.py", "line": 1, "column": 0}})
        graph["nodes"].append(second); graph["owner_structural_facts"].append({"owner_id": second["id"], "call_occurrences": 0, "direct_import_occurrences": {"project_local": 0, "non_project": 0}}); roots.append(second)
    for suffix, source, target in (("a", roots[0], roots[1]), ("b", roots[0], roots[1]), ("r", roots[1], roots[0]), ("s", roots[0], roots[0])):
        ref_id = f"import:{suffix}"; location = deepcopy(source["location"])
        graph["import_references"].append({"id": ref_id, "importer_id": source["id"], "kind": "import", "module": "", "name": target["qualified_name"], "alias": "x", "level": 0, "location": location, "resolution": "exact", "target_id": target["id"], "candidate_ids": []})
        graph["edges"].append({"id": f"imports:{ref_id}", "kind": "imports", "source_id": source["id"], "target_id": target["id"], "location": location})
    graph["project"]["fingerprint"] = graph_fingerprint(graph)
    payload = project_graph_view(graph, profile_id="dependency.architecture", profile_version=1)["payload"]
    imports = {edge["id"]: edge for edge in payload["edges"] if edge["kind"] == "imports"}
    assert imports[aggregate_import_edge_id(roots[0]["id"], roots[1]["id"])]["exact_occurrence_count"] == 2
    assert len(imports) == 3
    assert payload["import_resolution_counts"]["exact"] == 4
    assert len(payload["import_references"]) == 5


def test_projection_is_canonical_under_source_collection_permutations_and_metrics_rejects_it():
    graph = _graph(); permuted = deepcopy(graph)
    for collection in ("nodes", "edges", "import_references"): permuted[collection].reverse()
    first = project_graph_view(graph, profile_id="dependency.architecture", profile_version=1)
    assert first == project_graph_view(permuted, profile_id="dependency.architecture", profile_version=1)
    with pytest.raises(ValueError): calculate_graph_metrics(first)


@pytest.mark.parametrize("profile_id,version", [("dependency.architecture", 2), ("dependency.architecture", True), ("dependency.architecture.latest", 1)])
def test_no_profile_or_version_fallback(profile_id, version):
    with pytest.raises(ValueError, match="Unsupported"):
        project_graph_view(_graph(), profile_id=profile_id, profile_version=version)


def test_empty_projection_and_external_unresolved_occurrences_are_preserved():
    graph = _graph()
    graph["nodes"] = []
    graph["edges"] = []
    graph["import_references"] = []
    graph["callsites"] = []
    graph["type_references"] = []
    graph["owner_structural_facts"] = []
    graph["diagnostics"] = []
    graph["project"]["fingerprint"] = graph_fingerprint(graph)
    payload = project_graph_view(
        graph, profile_id="dependency.architecture", profile_version=1
    )["payload"]
    assert payload["nodes"] == payload["edges"] == payload["import_references"] == []
    assert payload["import_resolution_counts"] == {
        "exact": 0, "external": 0, "unresolved": 0,
    }

    graph = _graph()
    root = next(node for node in graph["nodes"] if node["kind"] in {"file", "module"})
    additions = [
        {"id": "import:external", "importer_id": root["id"], "kind": "import",
         "module": "", "name": "stdlib", "alias": None, "level": 0,
         "location": {"path": root["path"], "line": 50, "column": 0},
         "resolution": "external", "target_id": None, "candidate_ids": []},
        {"id": "import:unresolved", "importer_id": root["id"], "kind": "from",
         "module": "missing", "name": "thing", "alias": None, "level": 1,
         "location": {"path": root["path"], "line": 51, "column": 0},
         "resolution": "unresolved", "target_id": None, "candidate_ids": []},
    ]
    graph["import_references"].extend(additions)
    graph["project"]["fingerprint"] = graph_fingerprint(graph)
    payload = project_graph_view(graph, profile_id="dependency.architecture", profile_version=1)["payload"]
    assert payload["import_resolution_counts"] == {
        status: sum(row["resolution"] == status for row in graph["import_references"])
        for status in ("exact", "external", "unresolved")
    }
    projected = {row["id"]: row for row in payload["import_references"]}
    assert [projected[row["id"]] for row in additions] == additions


def test_source_validation_precedes_architecture_policy_and_profile_selection():
    graph = _graph()
    graph["nodes"][0]["path"] = "../escape.py"
    with pytest.raises(ValueError, match="Invalid Graph DTO"):
        project_graph_view(graph, profile_id="dependency.architecture", profile_version=2)


def test_dependency_architecture_projector_has_no_parser_or_metrics_core_imports():
    path = Path(__file__).with_name("dependency_architecture.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    imports += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
    forbidden = ("parser", "metrics")
    assert all(not any(name == root or name.startswith(root + ".") for root in forbidden) for name in imports)
