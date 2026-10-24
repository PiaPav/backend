from copy import deepcopy

import pytest

from graph_dto import graph_fingerprint
from graph_dto.test_contract import _semantics7_graph
from views import graph_summary_fingerprint, serialize_graph_summary, validate_graph_summary_v1
from views.projections import project_inventory_minimal_v1


def _summary():
    graph = _semantics7_graph()
    graph["project"]["fingerprint"] = graph_fingerprint(graph)
    return project_inventory_minimal_v1(graph)


def test_summary_round_trip_contract_and_serialization():
    summary = _summary()
    validate_graph_summary_v1(summary)
    assert serialize_graph_summary(summary).endswith(b"\n")
    assert summary["summary_fingerprint"] == graph_summary_fingerprint(summary)


@pytest.mark.parametrize("mutate,match", [
    (lambda value: value["payload"]["node_counts"].__setitem__("file", True), "non-negative integer"),
    (lambda value: value["payload"]["node_counts"].__setitem__("extra", 0), "exact fields"),
    (lambda value: value["payload"]["roots"][0].__setitem__("path", "../bad.py"), "relative POSIX"),
    (lambda value: value["completeness"]["preserves"].reverse(), "completeness"),
    (lambda value: value["source"].__setitem__("parser_semantics_version", True), "semantics_version"),
])
def test_validator_rejects_malformed_payload_and_metadata(mutate, match):
    summary = _summary()
    mutate(summary)
    with pytest.raises(ValueError, match=match):
        validate_graph_summary_v1(summary, verify_fingerprint=False)


def test_validator_rejects_stale_fingerprint():
    summary = deepcopy(_summary())
    summary["payload"]["node_counts"]["constant"] = 1
    with pytest.raises(ValueError, match="fingerprint does not match"):
        validate_graph_summary_v1(summary)
