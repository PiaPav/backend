from copy import deepcopy

import pytest

from graph_dto import graph_fingerprint
from views import (
    aggregate_package_grouping_v1, aggregate_package_id, decode_aggregate_packages_v2,
    materialize_graph_profile, project_graph_summary, serialize_graph_summary,
    validate_graph_summary_v1,
)
from views.projections import project_aggregate_packages_v2
from views.testdata import build_representative_packages_v1


def _summary(size="medium"):
    return project_aggregate_packages_v2(build_representative_packages_v1(size))


def test_projection_decodes_to_independently_asserted_populations_and_is_immutable():
    source = build_representative_packages_v1("medium")
    before = deepcopy(source)
    summary = project_aggregate_packages_v2(source)
    assert source == before
    decoded = decode_aggregate_packages_v2(summary["payload"])
    assert decoded["graph_kind"] == "quotient"
    assert len(decoded["nodes"]) == 5
    assert len(decoded["edges"]) == 8
    assert sum(node["file_count"] for node in decoded["nodes"]) == 15
    assert sum(node["declaration_count"] for node in decoded["nodes"]) == 25
    assert sum(node["class_count"] for node in decoded["nodes"]) == 10
    assert sum(node["abstract_class_count"] for node in decoded["nodes"]) == 5
    assert sum(node["import_occurrence_counts"]["external"] for node in decoded["nodes"]) == 5
    assert sum(node["import_occurrence_counts"]["unresolved"] for node in decoded["nodes"]) == 5
    assert sum(node["import_occurrence_counts"]["exact"] for node in decoded["nodes"]) == 26
    assert sum(edge["exact_import_occurrence_count"] for edge in decoded["edges"]) == 16
    assert all(edge["canonical_import_edge_count"] == edge["exact_import_occurrence_count"]
               for edge in decoded["edges"])


def test_permutation_determinism_empty_graph_and_explicit_dispatch():
    source = build_representative_packages_v1("medium")
    permuted = deepcopy(source)
    for field in ("nodes", "edges", "import_references"):
        permuted[field].reverse()
    assert project_aggregate_packages_v2(source) == project_aggregate_packages_v2(permuted)
    assert project_graph_summary(source, profile_id="aggregate.packages", profile_version=2) == _summary()
    assert materialize_graph_profile(source, profile_id="aggregate.packages", profile_version=2) == _summary()
    with pytest.raises(ValueError, match="Unsupported version"):
        project_graph_summary(source, profile_id="aggregate.packages", profile_version=1)

    empty = deepcopy(source)
    for field in ("nodes", "edges", "import_references", "type_references", "callsites",
                  "owner_structural_facts", "diagnostics"):
        empty[field] = []
    empty["project"]["fingerprint"] = graph_fingerprint(empty)
    assert project_aggregate_packages_v2(empty)["payload"] == {
        "graph_kind": "quotient", "wire_format": 2, "grouping_version": 1,
        "packages": [], "imports": [],
    }


def test_decoder_does_not_mutate_and_summary_uses_compact_serialization():
    summary = _summary()
    payload = deepcopy(summary["payload"])
    decode_aggregate_packages_v2(payload)
    assert payload == summary["payload"]
    validate_graph_summary_v1(summary)
    raw = serialize_graph_summary(summary)
    assert b"\n  " not in raw and raw.endswith(b"\n")


def test_mutating_exported_or_decoded_grouping_does_not_change_normative_behavior():
    expected_grouping = aggregate_package_grouping_v1()
    expected_id = aggregate_package_id("alpha")
    expected_summary = _summary()
    expected_fingerprint = expected_summary["summary_fingerprint"]

    exported = aggregate_package_grouping_v1()
    exported["path_policy"]["separator"] = "\\"
    exported["populations"].clear()
    decoded = decode_aggregate_packages_v2(expected_summary["payload"])
    decoded["package_grouping"]["descriptor_version"] = 999
    decoded["package_grouping"]["quotient_edges"].clear()

    subsequent_summary = _summary()
    subsequent_decoded = decode_aggregate_packages_v2(subsequent_summary["payload"])
    assert aggregate_package_id("alpha") == expected_id
    assert subsequent_summary == expected_summary
    assert subsequent_summary["summary_fingerprint"] == expected_fingerprint
    assert aggregate_package_grouping_v1() == expected_grouping
    assert subsequent_decoded["package_grouping"] == expected_grouping


@pytest.mark.parametrize("mutate,match", [
    (lambda p: p.__setitem__("wire_format", True), "unknown"),
    (lambda p: p.__setitem__("grouping_version", True), "unknown"),
    (lambda p: p["packages"][0].__setitem__(1, True), "integer"),
    (lambda p: p["packages"][0].append(0), "10 positional"),
    (lambda p: p["packages"].append(deepcopy(p["packages"][0])), "unique"),
    (lambda p: p["packages"].reverse(), "canonical package"),
    (lambda p: p["imports"][0].__setitem__(0, 999), "endpoint indexes"),
    (lambda p: p["imports"][0].__setitem__(0, True), "endpoint indexes"),
    (lambda p: p["imports"][0].__setitem__(2, True), "integer"),
    (lambda p: p["imports"][0].__setitem__(1, p["imports"][0][0]), "self-edge"),
    (lambda p: p["imports"].append(deepcopy(p["imports"][0])), "duplicate"),
    (lambda p: p["imports"].reverse(), "canonical edge"),
    (lambda p: p.__setitem__("wire_format", 1), "unknown"),
])
def test_strict_decoder_rejects_malformed_wire(mutate, match):
    payload = deepcopy(_summary()["payload"])
    mutate(payload)
    with pytest.raises(ValueError, match=match):
        decode_aggregate_packages_v2(payload)
