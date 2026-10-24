from copy import deepcopy

import pytest

from views import graph_view_fingerprint, serialize_graph_view, validate_graph_view_v1
from views.registry import profile_metadata


EXPECTED_COMPLETENESS = {
    "kind": "query_lossless",
    "preserves": [
        "canonical_declaration_nodes",
        "canonical_declaration_ownership",
    ],
    "omits": [
        "call_relations",
        "callable_complexity_facts",
        "callsites",
        "diagnostics",
        "edge_locations",
        "field_access_relations",
        "import_references",
        "import_relations",
        "node_locations",
        "owner_structural_facts",
        "type_references",
        "type_relations",
    ],
}


def _view():
    view = {
        "artifact_kind": "graph_view", "view_schema_version": 1,
        "profile": {"id": "structure.declarations", "version": 1},
        "source": {"graph_schema_version": 1, "parser_semantics_version": 7,
                   "graph_fingerprint": "a" * 64},
        "completeness": deepcopy(EXPECTED_COMPLETENESS),
        "payload": {
            "nodes": [
                {"id": "class:é.py:C", "kind": "class", "class_kind": "class",
                 "qualified_name": "é.C", "parent_id": "file:é.py", "path": "é.py"},
                {"id": "file:é.py", "kind": "file", "qualified_name": "é",
                 "parent_id": None, "path": "é.py"},
            ],
            "edges": [{"id": "contains:é", "kind": "contains",
                       "source_id": "file:é.py", "target_id": "class:é.py:C"}],
        }, "view_fingerprint": "0" * 64,
    }
    view["payload"]["nodes"].sort(key=lambda item: item["id"])
    view["view_fingerprint"] = graph_view_fingerprint(view)
    return view


def test_valid_view_and_deterministic_unicode_serialization():
    view = _view()
    validate_graph_view_v1(view)
    assert serialize_graph_view(view) == serialize_graph_view(deepcopy(view))
    assert b"\\u00e9" not in serialize_graph_view(view)
    assert serialize_graph_view(view).endswith(b"\n")
    assert not serialize_graph_view(view).endswith(b"\n\n")


@pytest.mark.parametrize("mutation,message", [
    (lambda v: v.__setitem__("extra", 1), "root"),
    (lambda v: v["profile"].__setitem__("id", "canonical.full"), "Unsupported"),
    (lambda v: v["profile"].__setitem__("version", True), "Unsupported"),
    (lambda v: v.__setitem__("view_schema_version", True), "Unsupported"),
    (lambda v: v["source"].__setitem__("parser_semantics_version", 6), "Unsupported"),
    (lambda v: v["source"].__setitem__("graph_fingerprint", "A" * 64), "lowercase"),
    (lambda v: v["completeness"]["omits"].pop(), "completeness"),
    (lambda v: v["payload"]["nodes"].reverse(), "sorted"),
    (lambda v: v["payload"]["nodes"].append(deepcopy(v["payload"]["nodes"][0])), "duplicate"),
    (lambda v: v["payload"]["edges"][0].__setitem__("target_id", "missing"), "dangling"),
    (lambda v: v["payload"]["nodes"][0].__setitem__("extra", 1), "invalid fields"),
    (lambda v: v["payload"]["nodes"][0].__setitem__("class_kind", "interface"), "class_kind"),
])
def test_strict_invalid_envelopes_are_rejected(mutation, message):
    view = _view()
    mutation(view)
    with pytest.raises(ValueError, match=message):
        validate_graph_view_v1(view, verify_fingerprint=False)


def test_ownership_cycle_synthetic_and_stale_fingerprint_are_rejected():
    view = _view()
    view["payload"]["nodes"][0]["parent_id"] = None
    with pytest.raises(ValueError, match="inconsistent"):
        validate_graph_view_v1(view, verify_fingerprint=False)

    view = _view()
    view["payload"]["nodes"][0]["synthetic"] = False
    with pytest.raises(ValueError, match="invalid fields"):
        validate_graph_view_v1(view, verify_fingerprint=False)

    view = _view()
    view["payload"]["nodes"][0]["qualified_name"] = "changed"
    with pytest.raises(ValueError, match="does not match"):
        validate_graph_view_v1(view)


def test_payload_arrays_must_be_lists():
    view = _view()
    view["payload"]["nodes"] = tuple(view["payload"]["nodes"])
    with pytest.raises(ValueError, match="arrays"):
        validate_graph_view_v1(view, verify_fingerprint=False)


def test_cycle_is_rejected_explicitly():
    view = _view()
    class_node, file_node = view["payload"]["nodes"]
    file_node["parent_id"] = class_node["id"]
    view["payload"]["edges"].append({
        "id": "contains:cycle", "kind": "contains",
        "source_id": class_node["id"], "target_id": file_node["id"],
    })
    view["payload"]["edges"].sort(key=lambda item: item["id"])
    with pytest.raises(ValueError, match="acyclic"):
        validate_graph_view_v1(view, verify_fingerprint=False)


def test_profile_registry_metadata_cannot_be_mutated_through_a_returned_value():
    expected = deepcopy(EXPECTED_COMPLETENESS)
    assert profile_metadata("structure.declarations", 1) == expected
    metadata = profile_metadata("structure.declarations", 1)
    try:
        metadata["omits"].append("injected")
        leaked = deepcopy(profile_metadata("structure.declarations", 1))
    finally:
        metadata.clear()
        metadata.update(expected)
    assert leaked == expected
