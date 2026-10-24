from copy import deepcopy

import pytest

from graph_dto import graph_fingerprint
from graph_dto.test_contract import _semantics7_graph
from views.projections import project_inventory_minimal_v1


def _graph():
    graph = _semantics7_graph()
    graph["project"]["fingerprint"] = graph_fingerprint(graph)
    return graph


def test_empty_graph_has_complete_all_zero_payload():
    graph = {
        "schema_version": 1, "parser_semantics_version": 7,
        "project": {"fingerprint": ""},
        "nodes": [], "edges": [], "callsites": [], "type_references": [],
        "import_references": [], "owner_structural_facts": [], "diagnostics": [],
    }
    graph["project"]["fingerprint"] = graph_fingerprint(graph)

    payload = project_inventory_minimal_v1(graph)["payload"]

    assert payload["roots"] == []
    assert set(payload["node_counts"].values()) == {0}
    assert payload["synthetic_method_count"] == 0
    assert payload["diagnostics"] == {"total": 0, "by_kind_status": []}
    assert all(
        set(counts.values()) == {0}
        for counts in payload["reference_resolution_counts"].values()
    )


def test_empty_occurrence_collections_are_zero_filled_and_source_is_unchanged():
    graph = _graph()
    original = deepcopy(graph)

    result = project_inventory_minimal_v1(graph)

    assert result["payload"]["node_counts"] == {
        "class": 1, "constant": 0, "field": 1, "file": 1,
        "function": 1, "method": 1, "module": 0,
    }
    assert result["payload"]["reference_resolution_counts"] == {
        "imports": {"exact": 0, "external": 1, "unresolved": 0},
        "types": {"ambiguous": 0, "exact": 0, "external": 0, "unresolved": 0},
        "callsites": {"ambiguous": 0, "dynamic": 0, "exact": 0, "external": 0, "unresolved": 0},
    }
    assert result["payload"]["synthetic_method_count"] == 0
    assert graph == original
    result["payload"]["roots"][0]["path"] = "changed.py"
    assert graph == original


def test_diagnostics_are_jointly_aggregated_and_sorted():
    graph = _graph()
    graph["diagnostics"] = [
        {"id": "diagnostic:1", "kind": "z", "status": "warning"},
        {"id": "diagnostic:2", "kind": "a", "status": "error"},
        {"id": "diagnostic:3", "kind": "z", "status": "warning"},
    ]
    graph["project"]["fingerprint"] = graph_fingerprint(graph)

    diagnostics = project_inventory_minimal_v1(graph)["payload"]["diagnostics"]

    assert diagnostics == {"total": 3, "by_kind_status": [
        {"kind": "a", "status": "error", "count": 1},
        {"kind": "z", "status": "warning", "count": 2},
    ]}


@pytest.mark.parametrize("field,value", [("kind", ""), ("status", None), ("kind", True)])
def test_invalid_diagnostic_categories_are_rejected(field, value):
    graph = _graph()
    graph["diagnostics"] = [{"id": "diagnostic:1", "kind": "parse", "status": "warning", field: value}]
    graph["project"]["fingerprint"] = graph_fingerprint(graph)
    with pytest.raises(ValueError, match="inventory.*diagnostic"):
        project_inventory_minimal_v1(graph)


def test_collection_permutations_produce_the_same_summary():
    graph = _graph()
    permuted = deepcopy(graph)
    permuted["nodes"].reverse()
    permuted["edges"].reverse()
    permuted["project"]["fingerprint"] = graph_fingerprint(permuted)
    assert project_inventory_minimal_v1(permuted) == project_inventory_minimal_v1(graph)


def test_resolution_counts_occurrences_not_aggregated_topology_and_counts_synthetic_methods():
    graph = _graph()
    file_id = "file:a.py"
    function_id = "function:a.py:1:0:f"
    class_id = "class:a.py:2:0:C"
    second_class_id = "class:a.py:8:0:D"
    field_id = "field:a.py:3:4:C.value"
    method_id = "method:a.py:4:4:C.read"
    location = {"path": "a.py", "line": 7, "column": 0}

    graph["nodes"].append({
        "id": second_class_id, "kind": "class", "class_kind": "class",
        "qualified_name": "a.D", "parent_id": file_id, "path": "a.py",
        "location": {"path": "a.py", "line": 8, "column": 0},
    })
    graph["edges"].append({
        "id": "contains:D", "kind": "contains", "source_id": file_id,
        "target_id": second_class_id,
    })

    method = next(node for node in graph["nodes"] if node["id"] == method_id)
    method["synthetic"] = True
    method.pop("complexity_facts")
    graph["owner_structural_facts"] = [
        fact for fact in graph["owner_structural_facts"] if fact["owner_id"] != method_id
    ]

    graph["import_references"].extend([
        {
            "id": "import:exact", "importer_id": file_id, "kind": "import",
            "module": "", "name": "a", "alias": None, "level": 0,
            "location": location, "resolution": "exact", "target_id": file_id,
            "candidate_ids": [],
        },
        {
            "id": "import:unresolved", "importer_id": file_id, "kind": "from",
            "module": "missing", "name": "value", "alias": None, "level": 1,
            "location": location, "resolution": "unresolved", "target_id": None,
            "candidate_ids": [],
        },
    ])
    graph["edges"].append({
        "id": "imports:import:exact", "kind": "imports", "source_id": file_id,
        "target_id": file_id, "location": location,
    })
    graph["owner_structural_facts"][0]["direct_import_occurrences"] = {
        "project_local": 1, "non_project": 2,
    }

    graph["type_references"] = [
        {"id": "type:exact", "owner_id": field_id, "role": "field_type", "expression": "C",
         "location": location, "resolution": "exact", "target_id": class_id, "candidate_ids": []},
        {"id": "type:ambiguous", "owner_id": field_id, "role": "field_type", "expression": "T",
         "location": location, "resolution": "ambiguous", "target_id": None,
         "candidate_ids": [class_id, second_class_id]},
        {"id": "type:external", "owner_id": field_id, "role": "field_type", "expression": "External",
         "location": location, "resolution": "external", "target_id": None, "candidate_ids": []},
        {"id": "type:unresolved", "owner_id": field_id, "role": "field_type", "expression": "Missing",
         "location": location, "resolution": "unresolved", "target_id": None, "candidate_ids": []},
    ]
    graph["edges"].append({
        "id": "field_type:C", "kind": "field_type", "source_id": field_id,
        "target_id": class_id,
    })

    def call(identifier, resolution, *, target=None, candidates=None):
        return {
            "id": identifier, "caller_id": function_id, "expression": "call()",
            "location": location, "syntactic_depth": 0, "resolution": resolution,
            "target_id": target, "candidate_ids": candidates or [], "awaited": False,
        }

    graph["callsites"] = [
        call("call:exact:1", "exact", target=method_id),
        call("call:exact:2", "exact", target=method_id),
        call("call:ambiguous", "ambiguous", candidates=[function_id, method_id]),
        call("call:external", "external"),
        call("call:dynamic", "dynamic"),
        call("call:unresolved", "unresolved"),
    ]
    graph["edges"].append({
        "id": "calls:repeated", "kind": "calls", "source_id": function_id,
        "target_id": method_id, "weight": 2,
    })
    next(fact for fact in graph["owner_structural_facts"] if fact["owner_id"] == function_id)[
        "call_occurrences"
    ] = 6
    graph["project"]["fingerprint"] = graph_fingerprint(graph)

    payload = project_inventory_minimal_v1(graph)["payload"]

    assert payload["reference_resolution_counts"] == {
        "imports": {"exact": 1, "external": 1, "unresolved": 1},
        "types": {"ambiguous": 1, "exact": 1, "external": 1, "unresolved": 1},
        "callsites": {"ambiguous": 1, "dynamic": 1, "exact": 2, "external": 1, "unresolved": 1},
    }
    assert payload["synthetic_method_count"] == 1
