"""Runtime and strict-wire regression tests for aggregate.overview/1."""
from __future__ import annotations

from copy import deepcopy

import pytest

from views import (decode_aggregate_overview_v1, project_graph_summary,
                   serialize_graph_summary, validate_graph_summary_v1)
from views.projections.aggregate_overview import _scc
from views.testdata import build_representative_overview_v1


def _summary():
    return project_graph_summary(build_representative_overview_v1("medium"),
                                 profile_id="aggregate.overview", profile_version=1)


def test_projection_decodes_and_isolated_descriptors_are_fresh() -> None:
    summary = _summary()
    first = decode_aggregate_overview_v1(summary["payload"])
    second = decode_aggregate_overview_v1(summary["payload"])
    first["top_k"]["limit"] = 0
    first["hotspots"]["files_by_fan_in"]["items"].clear()
    assert second["top_k"]["limit"] == 10
    assert second["hotspots"]["files_by_fan_in"]["items"]
    validate_graph_summary_v1(summary)


@pytest.mark.parametrize("mutation", [
    lambda p: p.update(extra=1),
    lambda p: p["totals"].__setitem__(0, True),
    lambda p: p["statuses"].__setitem__(0, -1),
    lambda p: p["rankings"][0].__setitem__(1, 99),
    lambda p: p["rankings"][0][3].append(p["rankings"][0][3][0]),
])
def test_decoder_rejects_malformed_wire(mutation) -> None:
    payload = deepcopy(_summary()["payload"])
    mutation(payload)
    with pytest.raises(ValueError, match="Invalid aggregate.overview"):
        decode_aggregate_overview_v1(payload)


@pytest.mark.parametrize("mutation", [
    lambda p: p["file_identities"].reverse(),
    lambda p: p["file_identities"].append(list(p["file_identities"][0])),
    lambda p: p["rankings"][0][3].reverse(),
    lambda p: p["rankings"][0][3][0].__setitem__(0, True),
])
def test_decoder_rejects_identity_and_order_invariant_violations(mutation) -> None:
    payload = deepcopy(_summary()["payload"])
    mutation(payload)
    with pytest.raises(ValueError, match="Invalid aggregate.overview"):
        decode_aggregate_overview_v1(payload)


def test_decoder_accepts_canonical_empty_graph_wire() -> None:
    payload = {"graph_kind": "overview", "wire_format": 1, "policy_version": 1,
               "totals": [0] * 19, "statuses": [0] * 12,
               "file_identities": [], "package_identities": [],
               "rankings": [[0, 0, False, []] for _ in range(3)]}
    decoded = decode_aggregate_overview_v1(payload)
    assert decoded["file_graph"] == {"vertices": 0, "edges": 0, "cyclic_components": 0}
    assert decoded["package_graph"] == {"vertices": 0, "edges": 0, "cyclic_components": 0}
    assert all(value == {"items": [], "returned_count": 0, "total_matching": 0,
                         "truncated": False} for value in decoded["hotspots"].values())


def test_projection_is_deterministic_and_does_not_mutate_source() -> None:
    graph = build_representative_overview_v1("medium")
    original = deepcopy(graph)
    expected = project_graph_summary(graph, profile_id="aggregate.overview", profile_version=1)
    assert graph == original
    for key in ("nodes", "import_references", "type_references", "callsites",
                "owner_structural_facts"):
        graph[key] = list(reversed(graph[key]))
    actual = project_graph_summary(graph, profile_id="aggregate.overview", profile_version=1)
    assert actual == expected
    assert original == build_representative_overview_v1("medium")


def test_scc_is_stack_safe_for_large_topologies() -> None:
    vertices = {str(index) for index in range(5000)}
    chain = {(str(index), str(index + 1)) for index in range(4999)}
    assert _scc(vertices, chain) == 0
    assert _scc(vertices, chain | {("4999", "0")}) == 1


@pytest.mark.parametrize("name", ["medium", "large"])
def test_runtime_artifact_meets_eight_percent_acceptance(name: str) -> None:
    graph = build_representative_overview_v1(name)
    summary = project_graph_summary(graph, profile_id="aggregate.overview", profile_version=1)
    import json
    source = json.dumps(graph, ensure_ascii=False, sort_keys=True,
                        separators=(",", ":")).encode("utf-8")
    artifact = serialize_graph_summary(summary)
    assert len(artifact) * 100 <= len(source) * 8
