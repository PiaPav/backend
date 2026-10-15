from copy import deepcopy

import pytest

from graph_dto import graph_fingerprint, validate_graph_v1


def _graph():
    graph = {
        "schema_version": 1, "parser_semantics_version": 1,
        "project": {"fingerprint": ""},
        "nodes": [
            {"id": "file:a.py", "kind": "file", "qualified_name": "a", "parent_id": None, "path": "a.py", "location": {"path": "a.py", "line": 1, "column": 0}},
            {"id": "function:a.py:1:0:f", "kind": "function", "qualified_name": "a.f", "parent_id": "file:a.py", "path": "a.py", "location": {"path": "a.py", "line": 1, "column": 0}},
        ],
        "edges": [{"id": "contains:a", "kind": "contains", "source_id": "file:a.py", "target_id": "function:a.py:1:0:f"}],
        "callsites": [], "diagnostics": [], "body": [],
    }
    graph["project"]["fingerprint"] = graph_fingerprint(graph)
    return graph


def test_fingerprint_ignores_body_fingerprint_and_collection_permutations():
    graph = _graph()
    changed = deepcopy(graph)
    changed["nodes"].reverse()
    changed["body"] = [{"anything": True}]
    changed["project"]["fingerprint"] = "not-input"
    assert graph_fingerprint(changed) == graph["project"]["fingerprint"]
    validate_graph_v1(graph)


def test_unknown_version_and_invalid_contains_are_rejected():
    graph = _graph()
    graph["parser_semantics_version"] = 3
    with pytest.raises(ValueError, match="Unsupported"):
        validate_graph_v1(graph)
    graph = _graph()
    graph["edges"].append({"id": "cycle", "kind": "contains", "source_id": "function:a.py:1:0:f", "target_id": "file:a.py"})
    graph["nodes"][0]["parent_id"] = "function:a.py:1:0:f"
    with pytest.raises(ValueError, match="acyclic"):
        validate_graph_v1(graph, verify_fingerprint=False)


def _semantics2_graph():
    graph = _graph()
    graph["parser_semantics_version"] = 2
    graph["type_references"] = []
    class_id = "class:a.py:2:0:C"
    field_id = "field:a.py:3:4:C.value"
    method_id = "method:a.py:4:4:C.read"
    graph["nodes"].extend([
        {"id": class_id, "kind": "class", "qualified_name": "a.C", "parent_id": "file:a.py", "path": "a.py", "location": {"path": "a.py", "line": 2, "column": 0}},
        {"id": field_id, "kind": "field", "qualified_name": "a.C.value", "parent_id": class_id, "path": "a.py", "location": {"path": "a.py", "line": 3, "column": 4}},
        {"id": method_id, "kind": "method", "qualified_name": "a.C.read", "parent_id": class_id, "path": "a.py", "location": {"path": "a.py", "line": 4, "column": 4}},
    ])
    graph["edges"].extend([
        {"id": "contains:C", "kind": "contains", "source_id": "file:a.py", "target_id": class_id},
        {"id": "contains:value", "kind": "contains", "source_id": class_id, "target_id": field_id},
        {"id": "contains:read", "kind": "contains", "source_id": class_id, "target_id": method_id},
    ])
    return graph


def test_semantics1_remains_compatible_without_type_references():
    validate_graph_v1(_graph(), verify_fingerprint=False)


def test_semantics2_requires_type_references_collection():
    graph = _graph()
    graph["parser_semantics_version"] = 2
    with pytest.raises(ValueError, match="type_references"):
        validate_graph_v1(graph, verify_fingerprint=False)


@pytest.mark.parametrize("source_id,target_id", [
    ("file:a.py", "function:a.py:1:0:f"),
    ("function:a.py:1:0:f", "file:a.py"),
])
def test_semantics2_imports_require_module_endpoints(source_id, target_id):
    graph = _semantics2_graph()
    graph["edges"].append({
        "id": "imports:invalid", "kind": "imports",
        "source_id": source_id, "target_id": target_id,
    })
    with pytest.raises(ValueError, match="imports endpoints"):
        validate_graph_v1(graph, verify_fingerprint=False)


def test_semantics2_validates_typed_reference_edge_correspondence_and_access_endpoints():
    graph = _semantics2_graph()
    class_id = "class:a.py:2:0:C"
    field_id = "field:a.py:3:4:C.value"
    method_id = "method:a.py:4:4:C.read"
    graph["type_references"] = [{
        "id": "type:1", "owner_id": field_id, "role": "field_type", "expression": "C",
        "location": {"path": "a.py", "line": 3, "column": 11}, "resolution": "exact",
        "target_id": class_id, "candidate_ids": [],
    }]
    graph["edges"].extend([
        {"id": "field_type:1", "kind": "field_type", "source_id": field_id, "target_id": class_id},
        {"id": "access:1", "kind": "accesses_field", "source_id": method_id, "target_id": field_id,
         "location": {"path": "a.py", "line": 5, "column": 15}},
    ])
    validate_graph_v1(graph, verify_fingerprint=False)
    graph["type_references"].clear()
    with pytest.raises(ValueError, match="typed relation"):
        validate_graph_v1(graph, verify_fingerprint=False)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda graph: graph.__setitem__("schema_version", True),
        lambda graph: graph.__setitem__("parser_semantics_version", True),
        lambda graph: graph["nodes"][0]["location"].__setitem__("line", True),
        lambda graph: graph["nodes"][0]["location"].__setitem__("column", False),
    ],
)
def test_boolean_values_are_not_accepted_as_integer_schema_fields(mutate):
    graph = _graph()
    mutate(graph)
    with pytest.raises(ValueError, match="Invalid Graph DTO v1"):
        validate_graph_v1(graph, verify_fingerprint=False)


def _exact_call_graph():
    graph = _graph()
    graph["callsites"] = [{"id": "call:1", "caller_id": "function:a.py:1:0:f",
                           "expression": "f()", "location": {"path": "a.py", "line": 2, "column": 0},
                           "syntactic_depth": 0, "resolution": "exact",
                           "target_id": "function:a.py:1:0:f", "candidate_ids": [], "awaited": False}]
    graph["edges"].append({"id": "calls:f", "kind": "calls", "source_id": "function:a.py:1:0:f",
                           "target_id": "function:a.py:1:0:f", "weight": 1})
    return graph


@pytest.mark.parametrize("mutate", [
    lambda graph: graph["callsites"][0].__setitem__("id", ""),
    lambda graph: graph["callsites"][0].__setitem__("awaited", 1),
    lambda graph: graph["callsites"][0].__setitem__("location", {"path": "../a.py", "line": 1, "column": 0}),
    lambda graph: graph["edges"][1].pop("weight"),
    lambda graph: graph["edges"][1].__setitem__("weight", 2),
    lambda graph: graph["callsites"].clear(),
])
def test_exact_callsites_and_aggregates_are_strictly_validated(mutate):
    graph = _exact_call_graph(); mutate(graph)
    with pytest.raises(ValueError, match="Invalid Graph DTO v1"):
        validate_graph_v1(graph, verify_fingerprint=False)


def test_declared_edge_location_is_validated():
    graph = _graph()
    graph["edges"][0]["location"] = {"path": "a.py", "line": 0, "column": 0}
    with pytest.raises(ValueError, match="location"):
        validate_graph_v1(graph, verify_fingerprint=False)


@pytest.mark.parametrize("mutate", [
    lambda graph: graph["callsites"][0].__setitem__("target_id", "file:a.py"),
    lambda graph: graph["edges"].append({"id": "calls:duplicate", "kind": "calls",
                                         "source_id": "function:a.py:1:0:f",
                                         "target_id": "function:a.py:1:0:f", "weight": 1}),
])
def test_callsite_edges_require_callable_endpoints_and_unique_aggregates(mutate):
    graph = _exact_call_graph()
    mutate(graph)
    with pytest.raises(ValueError, match="Invalid Graph DTO v1"):
        validate_graph_v1(graph, verify_fingerprint=False)


def test_file_is_a_valid_call_owner_but_never_a_call_target():
    graph = _exact_call_graph()
    graph["callsites"][0]["caller_id"] = "file:a.py"
    graph["edges"][1]["source_id"] = "file:a.py"
    validate_graph_v1(graph, verify_fingerprint=False)

    graph["callsites"][0]["target_id"] = "file:a.py"
    graph["edges"][1]["target_id"] = "file:a.py"
    with pytest.raises(ValueError, match="target"):
        validate_graph_v1(graph, verify_fingerprint=False)


@pytest.mark.parametrize("weight", [0, -1, True, 1.5])
def test_aggregated_call_weights_are_positive_integers(weight):
    graph = _exact_call_graph()
    graph["edges"][1]["weight"] = weight
    with pytest.raises(ValueError, match="weight"):
        validate_graph_v1(graph, verify_fingerprint=False)


@pytest.mark.parametrize("identifier,path", [
    ("file:other.py", "a.py"),
    ("file:/a.py", "/a.py"),
    ("file:a\\b.py", "a\\b.py"),
    ("file:../a.py", "../a.py"),
])
def test_file_node_id_is_derived_from_a_relative_posix_path(identifier, path):
    graph = _graph()
    graph["nodes"][0]["id"] = identifier
    graph["nodes"][0]["path"] = path
    with pytest.raises(ValueError, match="Invalid Graph DTO v1"):
        validate_graph_v1(graph, verify_fingerprint=False)


@pytest.mark.parametrize("candidates", [
    ["file:a.py", "function:a.py:1:0:f"],
    ["class:a.py:1:0:C", "function:a.py:1:0:f"],
    ["function:a.py:1:0:f", "missing"],
    ["function:a.py:1:0:f", "function:a.py:1:0:f"],
    ["function:z.py:1:0:z", "function:a.py:1:0:f"],
])
def test_ambiguous_candidates_are_sorted_unique_existing_callables(candidates):
    graph = _graph()
    graph["nodes"].append(
        {"id": "class:a.py:1:0:C", "kind": "class", "qualified_name": "a.C",
         "parent_id": None, "path": "a.py",
         "location": {"path": "a.py", "line": 1, "column": 0}}
    )
    graph["callsites"] = [{"id": "call:1", "caller_id": "function:a.py:1:0:f",
                           "expression": "x()", "location": {"path": "a.py", "line": 2, "column": 0},
                           "syntactic_depth": 0, "resolution": "ambiguous", "target_id": None,
                           "candidate_ids": candidates, "awaited": False}]
    with pytest.raises(ValueError, match="Invalid Graph DTO v1"):
        validate_graph_v1(graph, verify_fingerprint=False)


def test_valid_ambiguous_callable_candidates_are_accepted():
    graph = _graph()
    second = "function:a.py:2:0:g"
    graph["nodes"].append(
        {"id": second, "kind": "function", "qualified_name": "a.g",
         "parent_id": "file:a.py", "path": "a.py",
         "location": {"path": "a.py", "line": 2, "column": 0}}
    )
    graph["edges"].append(
        {"id": "contains:g", "kind": "contains", "source_id": "file:a.py", "target_id": second}
    )
    graph["callsites"] = [
        {"id": "call:1", "caller_id": "function:a.py:1:0:f", "expression": "candidate()",
         "location": {"path": "a.py", "line": 3, "column": 0}, "syntactic_depth": 0,
         "resolution": "ambiguous", "target_id": None,
         "candidate_ids": ["function:a.py:1:0:f", second], "awaited": False}
    ]

    validate_graph_v1(graph, verify_fingerprint=False)
