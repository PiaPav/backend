from copy import deepcopy

import pytest

from graph_dto import graph_fingerprint, validate_graph_v1
from graph_dto.test_contract import _semantics7_graph
from metrics import calculate_graph_metrics
from views import materialize_graph_profile, project_graph_summary, project_graph_view


def _graph():
    graph = _semantics7_graph()
    graph["compatible_extension"] = {"values": ["preserved"]}
    graph["project"]["fingerprint"] = graph_fingerprint(graph)
    return graph


def test_canonical_full_preserves_complete_graph_as_an_independent_copy():
    graph = _graph()
    original = deepcopy(graph)

    result = materialize_graph_profile(
        graph, profile_id="canonical.full", profile_version=1
    )

    assert result == graph
    assert result is not graph
    assert result["project"] is not graph["project"]
    assert result["nodes"] is not graph["nodes"]
    assert result["compatible_extension"] is not graph["compatible_extension"]
    result["nodes"][0]["qualified_name"] = "changed"
    result["compatible_extension"]["values"].append("changed")
    assert graph == original


def test_canonical_full_is_a_graph_dto_consumable_by_metrics_without_view_envelope():
    result = materialize_graph_profile(
        _graph(), profile_id="canonical.full", profile_version=1
    )

    validate_graph_v1(result)
    calculate_graph_metrics(result)
    assert "artifact_kind" not in result
    assert "view_fingerprint" not in result


@pytest.mark.parametrize("profile_id,version", [
    ("canonical.full", 2),
    ("canonical.full", True),
    ("structure.declarations", 2),
    ("structure.declarations", True),
    ("inventory.minimal", 2),
    ("inventory.minimal", True),
    ("dependency.files", 2),
    ("dependency.files", True),
    ("dependency.architecture", 2),
    ("dependency.architecture", True),
    ("unknown", 1),
])
def test_unified_api_has_no_profile_or_version_fallback(profile_id, version):
    with pytest.raises(ValueError, match="Unsupported"):
        materialize_graph_profile(_graph(), profile_id=profile_id, profile_version=version)


def test_canonical_policy_rejects_valid_older_parser_semantics():
    graph = _graph()
    graph["parser_semantics_version"] = 6
    graph["project"]["fingerprint"] = graph_fingerprint(graph)
    validate_graph_v1(graph)

    with pytest.raises(ValueError, match="semantics 7"):
        materialize_graph_profile(graph, profile_id="canonical.full", profile_version=1)


def test_source_validation_precedes_profile_selection():
    graph = _graph()
    graph["nodes"][0]["path"] = "../bad.py"

    with pytest.raises(ValueError, match="Invalid Graph DTO"):
        materialize_graph_profile(graph, profile_id="unknown", profile_version=1)


def test_unified_structure_profile_matches_existing_graph_view_api():
    graph = _graph()

    assert materialize_graph_profile(
        graph, profile_id="structure.declarations", profile_version=1
    ) == project_graph_view(
        graph, profile_id="structure.declarations", profile_version=1
    )


def test_unified_dependency_architecture_matches_graph_view_api():
    graph = _graph()
    assert materialize_graph_profile(graph, profile_id="dependency.architecture", profile_version=1) == project_graph_view(graph, profile_id="dependency.architecture", profile_version=1)


def test_graph_view_api_continues_to_reject_canonical_profile():
    with pytest.raises(ValueError, match="Unsupported graph view profile"):
        project_graph_view(_graph(), profile_id="canonical.full", profile_version=1)


def test_unified_inventory_profile_matches_summary_gateway():
    graph = _graph()
    assert materialize_graph_profile(
        graph, profile_id="inventory.minimal", profile_version=1
    ) == project_graph_summary(
        graph, profile_id="inventory.minimal", profile_version=1
    )


def test_specialized_gateways_do_not_accept_the_other_artifact_kinds():
    with pytest.raises(ValueError, match="Unsupported graph view profile"):
        project_graph_view(_graph(), profile_id="inventory.minimal", profile_version=1)
    with pytest.raises(ValueError, match="Unsupported graph summary profile"):
        project_graph_summary(_graph(), profile_id="structure.declarations", profile_version=1)
    with pytest.raises(ValueError, match="Unsupported graph summary profile"):
        project_graph_summary(_graph(), profile_id="dependency.files", profile_version=1)


def test_metrics_rejects_graph_summary():
    summary = project_graph_summary(
        _graph(), profile_id="inventory.minimal", profile_version=1
    )
    with pytest.raises(ValueError, match="Unsupported graph schema_version"):
        calculate_graph_metrics(summary)
