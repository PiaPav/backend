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
    graph["parser_semantics_version"] = 8
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


def _semantics3_graph():
    graph = _semantics2_graph()
    graph["parser_semantics_version"] = 3
    facts = {
        "span": {
            "start": {"path": "a.py", "line": 1, "column": 0},
            "end": {"path": "a.py", "line": 2, "column": 8},
        },
        "is_async": False,
        "controls": [],
        "occurrences": [{"kind": "statement", "location": {"path": "a.py", "line": 2, "column": 4}}],
    }
    graph["nodes"][1]["complexity_facts"] = facts
    method = next(node for node in graph["nodes"] if node["kind"] == "method")
    method["complexity_facts"] = {
        **deepcopy(facts),
        "span": {
            "start": deepcopy(method["location"]),
            "end": {"path": "a.py", "line": 5, "column": 8},
        },
        "occurrences": [],
        "controls": [{
            "kind": "boolean", "parent_index": None,
            "location": {"path": "a.py", "line": 5, "column": 8},
            "operand_count": 2, "case_count": 0, "filter_count": 0,
        }],
    }
    return graph


def test_semantics3_requires_facts_only_on_real_callables():
    graph = _semantics3_graph()
    validate_graph_v1(graph, verify_fingerprint=False)
    graph["nodes"][1].pop("complexity_facts")
    with pytest.raises(ValueError, match="complexity_facts"):
        validate_graph_v1(graph, verify_fingerprint=False)


def _semantics4_graph():
    graph = _semantics3_graph()
    graph["parser_semantics_version"] = 4
    graph["import_references"] = [{
        "id": "import:a.py:1:0:1", "importer_id": "file:a.py",
        "kind": "import", "module": "", "name": "third_party", "alias": None,
        "level": 0, "location": {"path": "a.py", "line": 1, "column": 0},
        "resolution": "external", "target_id": None, "candidate_ids": [],
    }]
    return graph


def _semantics5_graph():
    graph = _semantics4_graph()
    graph["parser_semantics_version"] = 5
    for node in graph["nodes"]:
        if node["kind"] == "class":
            node["class_kind"] = "class"
    return graph


def _semantics6_graph():
    graph = _semantics5_graph()
    graph["parser_semantics_version"] = 6
    graph["owner_structural_facts"] = [
        {
            "owner_id": "file:a.py",
            "call_occurrences": 0,
            "direct_import_occurrences": {"project_local": 0, "non_project": 1},
        },
        {"owner_id": "function:a.py:1:0:f", "call_occurrences": 0},
        {"owner_id": "method:a.py:4:4:C.read", "call_occurrences": 0},
    ]
    return graph


def _semantics7_graph():
    graph = _semantics6_graph()
    graph["parser_semantics_version"] = 7
    del graph["body"]
    return graph


def test_semantics7_requires_bodyless_canonical_graph():
    graph = _semantics7_graph()
    validate_graph_v1(graph, verify_fingerprint=False)

    for body in ([], [{"legacy": True}], None):
        invalid = deepcopy(graph)
        invalid["body"] = body
        with pytest.raises(ValueError, match="body is not allowed"):
            validate_graph_v1(invalid, verify_fingerprint=False)


def test_semantics6_body_remains_an_optional_array():
    graph = _semantics6_graph()
    validate_graph_v1(graph, verify_fingerprint=False)
    del graph["body"]
    validate_graph_v1(graph, verify_fingerprint=False)
    graph["body"] = {}
    with pytest.raises(ValueError, match="body must be an array"):
        validate_graph_v1(graph, verify_fingerprint=False)


def test_semantics6_requires_complete_strict_structural_facts_but_not_body():
    graph = _semantics6_graph()
    del graph["body"]
    validate_graph_v1(graph, verify_fingerprint=False)

    for mutate, message in (
        (lambda value: value.pop(), "exactly every structural owner"),
        (lambda value: value[0].__setitem__("call_occurrences", True), "call_occurrences"),
        (lambda value: value[1].__setitem__("direct_import_occurrences", {}), "invalid fields"),
    ):
        invalid = _semantics6_graph()
        mutate(invalid["owner_structural_facts"])
        with pytest.raises(ValueError, match=message):
            validate_graph_v1(invalid, verify_fingerprint=False)


def test_semantics6_body_is_not_part_of_graph_fingerprint():
    graph = _semantics6_graph()
    without_body = deepcopy(graph)
    del without_body["body"]
    changed_body = deepcopy(graph)
    changed_body["body"] = [{"legacy": "changed"}]
    assert graph_fingerprint(graph) == graph_fingerprint(without_body)
    assert graph_fingerprint(graph) == graph_fingerprint(changed_body)


def test_semantics5_requires_legacy_body_and_class_kind():
    graph = _semantics5_graph()
    validate_graph_v1(graph, verify_fingerprint=False)

    del graph["body"]
    with pytest.raises(ValueError, match="body must be an array"):
        validate_graph_v1(graph, verify_fingerprint=False)

    graph = _semantics5_graph()
    del next(node for node in graph["nodes"] if node["kind"] == "class")["class_kind"]
    with pytest.raises(ValueError, match="class_kind is invalid"):
        validate_graph_v1(graph, verify_fingerprint=False)


def test_semantics5_restricts_class_kind_and_synthetic_to_their_node_kinds():
    graph = _semantics5_graph()
    function = next(node for node in graph["nodes"] if node["kind"] == "function")
    function["class_kind"] = "class"
    with pytest.raises(ValueError, match="class_kind is only allowed on classes"):
        validate_graph_v1(graph, verify_fingerprint=False)

    graph = _semantics5_graph()
    function = next(node for node in graph["nodes"] if node["kind"] == "function")
    function["synthetic"] = False
    with pytest.raises(ValueError, match="synthetic is only allowed on methods"):
        validate_graph_v1(graph, verify_fingerprint=False)


def test_semantics4_rejects_constant_nodes_from_its_legacy_vocabulary():
    graph = _semantics4_graph()
    graph["nodes"].append({
        "id": "constant:a.py:1:0:A:1", "kind": "constant",
        "qualified_name": "a.A", "parent_id": None, "path": "a.py",
        "location": {"path": "a.py", "line": 1, "column": 0},
    })
    with pytest.raises(ValueError, match=r"nodes\[.*\]\.kind is invalid"):
        validate_graph_v1(graph, verify_fingerprint=False)


@pytest.mark.parametrize("kind", ["constant", "class", "function"])
def test_semantics5_rejects_orphan_owned_nodes(kind):
    graph = _semantics5_graph()
    if kind == "constant":
        graph["nodes"].append({
            "id": "constant:a.py:8:0:A:1", "kind": kind,
            "qualified_name": "a.A", "parent_id": None, "path": "a.py",
            "location": {"path": "a.py", "line": 8, "column": 0},
        })
    else:
        node = next(item for item in graph["nodes"] if item["kind"] == kind)
        node["parent_id"] = None
        graph["edges"] = [edge for edge in graph["edges"] if edge["target_id"] != node["id"]]
    with pytest.raises(ValueError, match="invalid owner|exactly one owner"):
        validate_graph_v1(graph, verify_fingerprint=False)


@pytest.mark.parametrize("field,value", [("path", "other.py"), ("location", {"path": "other.py", "line": 2, "column": 0})])
def test_semantics5_rejects_owned_node_path_or_location_mismatch(field, value):
    graph = _semantics5_graph()
    class_node = next(node for node in graph["nodes"] if node["kind"] == "class")
    class_node[field] = value
    with pytest.raises(ValueError, match="path must match|location path must match"):
        validate_graph_v1(graph, verify_fingerprint=False)


def test_semantics5_rejects_owner_kind_mismatch_and_synthetic_non_method():
    graph = _semantics5_graph()
    function = next(node for node in graph["nodes"] if node["kind"] == "function")
    class_node = next(node for node in graph["nodes"] if node["kind"] == "class")
    function["parent_id"] = class_node["id"]
    next(edge for edge in graph["edges"] if edge["target_id"] == function["id"])["source_id"] = class_node["id"]
    with pytest.raises(ValueError, match="contains endpoints|invalid owner"):
        validate_graph_v1(graph, verify_fingerprint=False)

    graph = _semantics5_graph()
    next(node for node in graph["nodes"] if node["kind"] == "class")["synthetic"] = True
    with pytest.raises(ValueError, match="synthetic is only allowed on methods"):
        validate_graph_v1(graph, verify_fingerprint=False)


def test_semantics5_rejects_file_containing_module_with_a_different_path():
    graph = _semantics5_graph()
    module_id = "module:package"
    graph["nodes"].append({
        "id": module_id, "kind": "module", "qualified_name": "package",
        "parent_id": "file:a.py", "path": "package/__init__.py",
        "location": {"path": "package/__init__.py", "line": 1, "column": 0},
    })
    graph["edges"].append({
        "id": "contains:module", "kind": "contains",
        "source_id": "file:a.py", "target_id": module_id,
    })
    class_node = next(node for node in graph["nodes"] if node["kind"] == "class")
    class_node["parent_id"] = module_id
    next(edge for edge in graph["edges"] if edge["target_id"] == class_node["id"])["source_id"] = module_id

    with pytest.raises(ValueError, match="canonical root"):
        validate_graph_v1(graph, verify_fingerprint=False)


def test_semantics5_accepts_a_parentless_root_module():
    graph = _semantics5_graph()
    graph["nodes"].append({
        "id": "module:package", "kind": "module", "qualified_name": "package",
        "parent_id": None, "path": "package/__init__.py",
        "location": {"path": "package/__init__.py", "line": 1, "column": 0},
    })

    validate_graph_v1(graph, verify_fingerprint=False)


def test_semantics4_requires_and_validates_import_references():
    graph = _semantics4_graph()
    validate_graph_v1(graph, verify_fingerprint=False)

    graph["import_references"][0]["resolution"] = "unresolved"
    graph["import_references"][0]["level"] = 1
    graph["import_references"][0]["kind"] = "from"
    validate_graph_v1(graph, verify_fingerprint=False)

    graph["import_references"][0]["target_id"] = "file:a.py"
    with pytest.raises(ValueError, match="non-exact"):
        validate_graph_v1(graph, verify_fingerprint=False)


def test_semantics4_exact_import_reference_and_edge_are_one_to_one():
    graph = _semantics4_graph()
    reference = graph["import_references"][0]
    reference.update({"name": "a", "resolution": "exact", "target_id": "file:a.py"})
    graph["edges"].append({
        "id": f"imports:{reference['id']}", "kind": "imports",
        "source_id": "file:a.py", "target_id": "file:a.py",
        "location": deepcopy(reference["location"]),
    })
    validate_graph_v1(graph, verify_fingerprint=False)

    graph["edges"][-1]["id"] = "imports:orphan"
    with pytest.raises(ValueError, match="exact resolution"):
        validate_graph_v1(graph, verify_fingerprint=False)


def test_semantics4_import_edge_location_and_resolution_combinations_are_strict():
    graph = _semantics4_graph()
    reference = graph["import_references"][0]
    reference.update({"name": "a", "resolution": "exact", "target_id": "file:a.py"})
    graph["edges"].append({
        "id": f"imports:{reference['id']}", "kind": "imports",
        "source_id": "file:a.py", "target_id": "file:a.py",
        "location": {"path": "a.py", "line": 2, "column": 0},
    })
    with pytest.raises(ValueError, match="does not match"):
        validate_graph_v1(graph, verify_fingerprint=False)

    for status, level in (("external", 1), ("unresolved", 0)):
        graph = _semantics4_graph()
        graph["import_references"][0].update({
            "kind": "from", "module": "a", "resolution": status, "level": level,
        })
        with pytest.raises(ValueError, match=status):
            validate_graph_v1(graph, verify_fingerprint=False)


def test_semantics4_allows_star_from_import_but_rejects_empty_absolute_from():
    graph = _semantics4_graph()
    graph["import_references"][0].update({
        "kind": "from", "module": "package", "name": "*",
    })
    validate_graph_v1(graph, verify_fingerprint=False)
    graph["import_references"][0]["module"] = ""
    with pytest.raises(ValueError, match="requires a module"):
        validate_graph_v1(graph, verify_fingerprint=False)


@pytest.mark.parametrize("value", [1, 0, "true", None])
def test_semantics3_optional_synthetic_flag_must_be_boolean(value):
    graph = _semantics3_graph()
    graph["nodes"][1]["synthetic"] = value
    with pytest.raises(ValueError, match=r"nodes\[1\]\.synthetic must be a boolean"):
        validate_graph_v1(graph, verify_fingerprint=False)


@pytest.mark.parametrize("mutate", [
    lambda facts: facts["controls"][0].__setitem__("parent_index", 0),
    lambda facts: facts["controls"][0].__setitem__("operand_count", 1),
    lambda facts: facts["controls"][0]["location"].__setitem__("line", 99),
    lambda facts: facts["span"]["end"].__setitem__("path", "other.py"),
])
def test_semantics3_strictly_validates_complexity_fact_references_cardinalities_and_spans(mutate):
    graph = _semantics3_graph()
    method = next(node for node in graph["nodes"] if node["kind"] == "method")
    mutate(method["complexity_facts"])
    with pytest.raises(ValueError, match="complexity_facts"):
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
