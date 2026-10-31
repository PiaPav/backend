"""Consumer-contract regression tests for explicit profile selection."""
from __future__ import annotations

from copy import deepcopy

import pytest

from views import (
    ProfileCompletenessError,
    materialize_graph_profile,
    materialize_metrics_profile,
    validate_graph_artifact_for_consumer,
    validate_metrics_artifact_for_consumer,
    validate_sibling_artifacts,
)
from views.testdata.representative_graph_v2 import build_representative_graph_v2
from views.testdata.test_representative_metrics_v1 import build_representative_metrics_v1


def _artifacts() -> tuple[dict, dict, dict]:
    graph = build_representative_graph_v2("medium")
    metrics_source = build_representative_metrics_v1("medium")
    graph_view = materialize_graph_profile(
        graph, profile_id="calls.detailed", profile_version=1
    )
    metrics_view = materialize_metrics_profile(
        metrics_source, profile_id="metrics.overview", profile_version=1
    )
    return graph, graph_view, metrics_view


def test_graph_view_summary_canonical_and_metrics_are_accepted() -> None:
    graph, graph_view, metrics_view = _artifacts()
    summary = materialize_graph_profile(
        graph, profile_id="inventory.minimal", profile_version=1
    )
    validate_graph_artifact_for_consumer(
        graph_view, profile_id="calls.detailed", profile_version=1,
        required_preserves="canonical_callsites",
    )
    validate_graph_artifact_for_consumer(
        summary, profile_id="inventory.minimal", profile_version=1,
        required_preserves=("node_kind_counts",),
    )
    validate_graph_artifact_for_consumer(
        graph, profile_id="canonical.full", profile_version=1,
        required_preserves=("unknown_capability_is_allowed_for_canonical",),
    )
    validate_metrics_artifact_for_consumer(
        metrics_view, profile_id="metrics.overview", profile_version=1,
        required_preserves=("project_size",),
    )
    metrics_full = build_representative_metrics_v1("medium")
    validate_metrics_artifact_for_consumer(
        metrics_full, profile_id="metrics.full", profile_version=1,
        required_preserves=("any_capability_is_allowed_for_full",),
    )


def test_metrics_full_and_view_are_not_interchangeable() -> None:
    _, _, metrics_view = _artifacts()
    metrics_full = build_representative_metrics_v1("medium")
    with pytest.raises(ValueError):
        validate_metrics_artifact_for_consumer(
            metrics_view, profile_id="metrics.full", profile_version=1,
            required_preserves=(),
        )
    with pytest.raises(ValueError):
        validate_metrics_artifact_for_consumer(
            metrics_full, profile_id="metrics.overview", profile_version=1,
            required_preserves=(),
        )


def test_exact_selection_types_and_completeness_error_fields() -> None:
    _, graph_view, metrics_view = _artifacts()
    with pytest.raises(ValueError):
        validate_graph_artifact_for_consumer(
            graph_view, profile_id="calls.topology", profile_version=1,
            required_preserves=(),
        )
    with pytest.raises(ValueError):
        validate_graph_artifact_for_consumer(
            graph_view, profile_id="calls.detailed", profile_version=True,
            required_preserves=(),
        )
    with pytest.raises(ValueError):
        validate_graph_artifact_for_consumer(
            graph_view, profile_id="calls.detailed", profile_version="1",
            required_preserves=(),
        )
    with pytest.raises(ValueError):
        validate_graph_artifact_for_consumer(
            graph_view, profile_id="unknown.profile", profile_version=1,
            required_preserves=(),
        )
    with pytest.raises(ProfileCompletenessError) as caught:
        validate_graph_artifact_for_consumer(
            graph_view, profile_id="calls.detailed", profile_version=1,
            required_preserves=("z_unknown", "a_unknown", "z_unknown"),
        )
    assert caught.value.required_preserves == ("a_unknown", "z_unknown")
    assert caught.value.missing_preserves == ("a_unknown", "z_unknown")
    assert caught.value.profile_id == "calls.detailed"
    assert caught.value.profile_version == 1
    with pytest.raises(TypeError):
        validate_graph_artifact_for_consumer(
            graph_view, profile_id="calls.detailed", profile_version=1,
            required_preserves=(True,),
        )
    for profile_id, profile_version in (
        (True, 1), ("metrics.overview", True), ("metrics.overview", "1"),
        ("unknown.profile", 1),
    ):
        with pytest.raises(ValueError):
            validate_metrics_artifact_for_consumer(
                metrics_view, profile_id=profile_id, profile_version=profile_version,
                required_preserves=(),
            )


def test_whole_artifact_validation_precedes_completeness() -> None:
    _, graph_view, metrics_view = _artifacts()
    for artifact, validate, profile_id in (
        (graph_view, validate_graph_artifact_for_consumer, "calls.detailed"),
        (metrics_view, validate_metrics_artifact_for_consumer, "metrics.overview"),
    ):
        malformed = deepcopy(artifact)
        malformed["unexpected"] = True
        with pytest.raises(ValueError) as caught:
            validate(
                malformed, profile_id=profile_id, profile_version=1,
                required_preserves=("missing_capability",),
            )
        assert not isinstance(caught.value, ProfileCompletenessError)


def test_strict_tampering_and_inputs_are_not_mutated() -> None:
    graph, graph_view, metrics_view = _artifacts()
    original_canonical = deepcopy(graph)
    original_graph, original_metrics = deepcopy(graph_view), deepcopy(metrics_view)
    tampered = deepcopy(graph_view)
    tampered["unexpected"] = True
    with pytest.raises(ValueError):
        validate_graph_artifact_for_consumer(
            tampered, profile_id="calls.detailed", profile_version=1,
            required_preserves=(),
        )
    validate_metrics_artifact_for_consumer(
        metrics_view, profile_id="metrics.overview", profile_version=1,
        required_preserves=(),
    )
    validate_graph_artifact_for_consumer(
        graph_view, profile_id="calls.detailed", profile_version=1,
        required_preserves=(),
    )
    validate_graph_artifact_for_consumer(
        graph, profile_id="canonical.full", profile_version=1,
        required_preserves=("globally_lossless",),
    )
    assert graph == original_canonical
    assert graph_view == original_graph
    assert metrics_view == original_metrics


def test_siblings_use_source_identity_not_own_fingerprints() -> None:
    graph, graph_view, metrics_view = _artifacts()
    assert graph_view["view_fingerprint"] != metrics_view["view_fingerprint"]
    graph_fingerprint = graph_view["source"]["graph_fingerprint"]
    assert validate_sibling_artifacts(
        graph_view, metrics_view,
        graph_profile_id="calls.detailed", graph_profile_version=1,
        graph_required_preserves=(), metrics_profile_id="metrics.overview",
        metrics_profile_version=1, metrics_required_preserves=(),
    ) == graph_fingerprint
    metrics_full = build_representative_metrics_v1("medium")
    assert validate_sibling_artifacts(
        graph, metrics_full,
        graph_profile_id="canonical.full", graph_profile_version=1,
        graph_required_preserves=(), metrics_profile_id="metrics.full",
        metrics_profile_version=1, metrics_required_preserves=("anything",),
    ) == graph_fingerprint
    mismatched_full = deepcopy(metrics_full)
    mismatched_full["input"]["graph_fingerprint"] = "0" * 64
    with pytest.raises(ValueError, match="different source graph fingerprints"):
        validate_sibling_artifacts(
            graph, mismatched_full,
            graph_profile_id="canonical.full", graph_profile_version=1,
            graph_required_preserves=(), metrics_profile_id="metrics.full",
            metrics_profile_version=1, metrics_required_preserves=(),
        )
    assert validate_sibling_artifacts(
        graph, metrics_view,
        graph_profile_id="canonical.full", graph_profile_version=1,
        graph_required_preserves=(), metrics_profile_id="metrics.overview",
        metrics_profile_version=1, metrics_required_preserves=(),
    ) == graph_fingerprint
    mismatched = deepcopy(metrics_view)
    mismatched["source"]["graph_fingerprint"] = "0" * 64
    from views.metrics_contract import metrics_view_fingerprint
    mismatched["view_fingerprint"] = metrics_view_fingerprint(mismatched)
    with pytest.raises(ValueError, match="different source graph fingerprints"):
        validate_sibling_artifacts(
            graph_view, mismatched,
            graph_profile_id="calls.detailed", graph_profile_version=1,
            graph_required_preserves=(), metrics_profile_id="metrics.overview",
            metrics_profile_version=1, metrics_required_preserves=(),
        )


def test_retry_is_explicit_and_does_not_materialize_another_profile() -> None:
    graph, minimal, _ = _artifacts()
    minimal = materialize_graph_profile(
        graph, profile_id="inventory.minimal", profile_version=1
    )
    with pytest.raises(ProfileCompletenessError):
        validate_graph_artifact_for_consumer(
            minimal, profile_id="inventory.minimal", profile_version=1,
            required_preserves=("canonical_callsites",),
        )
    detailed = materialize_graph_profile(
        graph, profile_id="calls.detailed", profile_version=1
    )
    validate_graph_artifact_for_consumer(
        detailed, profile_id="calls.detailed", profile_version=1,
        required_preserves=("canonical_callsites",),
    )
