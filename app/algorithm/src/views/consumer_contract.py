"""Validation helpers for consumers of explicitly selected profile artifacts."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from graph_dto import validate_graph_v1

from .contract import validate_graph_view_v1
from .metrics_contract import validate_metrics_source_v1, validate_metrics_view_v1
from .registry import (
    metrics_profile_metadata,
    profile_metadata,
    select_graph_profile,
    select_metrics_profile,
    summary_profile_metadata,
)
from .summary_contract import validate_graph_summary_v1


class ProfileCompletenessError(ValueError):
    """The selected profile does not preserve all consumer capabilities."""

    def __init__(
        self,
        profile_id: str,
        profile_version: int,
        required_preserves: tuple[str, ...],
        missing_preserves: tuple[str, ...],
    ) -> None:
        self.profile_id = profile_id
        self.profile_version = profile_version
        self.required_preserves = required_preserves
        self.missing_preserves = missing_preserves
        super().__init__(
            f"Profile {profile_id!r} version {profile_version!r} does not preserve "
            f"required capabilities: {', '.join(missing_preserves)}"
        )


def _required_capabilities(required_preserves: object) -> tuple[str, ...]:
    if isinstance(required_preserves, str):
        values: Iterable[object] = (required_preserves,)
    elif isinstance(required_preserves, Mapping) or not isinstance(required_preserves, Iterable):
        raise TypeError("required_preserves must be a string or an iterable of strings")
    else:
        values = required_preserves
    capabilities: set[str] = set()
    for capability in values:
        if not isinstance(capability, str):
            raise TypeError("required_preserves capabilities must be strings")
        if not capability:
            raise ValueError("required_preserves capabilities must be non-empty strings")
        capabilities.add(capability)
    return tuple(sorted(capabilities))


def _check_completeness(
    *,
    profile_id: str,
    profile_version: int,
    required_preserves: tuple[str, ...],
    available_preserves: object,
) -> None:
    available = set(available_preserves)  # registry metadata is trusted, fresh data
    missing = tuple(sorted(set(required_preserves) - available))
    if missing:
        raise ProfileCompletenessError(
            profile_id, profile_version, required_preserves, missing
        )


def validate_graph_artifact_for_consumer(
    artifact: Mapping[str, Any],
    *,
    profile_id: str,
    profile_version: int,
    required_preserves: object,
) -> None:
    """Strictly validate one exact graph profile and its consumer capabilities."""
    required = _required_capabilities(required_preserves)
    artifact_kind = select_graph_profile(profile_id, profile_version)
    if artifact_kind == "canonical":
        validate_graph_v1(artifact)
        if artifact.get("schema_version") != 1 or artifact.get("parser_semantics_version") != 7:
            raise ValueError(
                "canonical.full v1 requires Graph DTO schema 1 / parser semantics 7"
            )
        return
    if artifact_kind == "graph_view":
        validate_graph_view_v1(artifact)
        metadata = profile_metadata(profile_id, profile_version)
    else:
        validate_graph_summary_v1(artifact)
        metadata = summary_profile_metadata(profile_id, profile_version)
    if artifact["profile"] != {"id": profile_id, "version": profile_version}:
        raise ValueError("Graph artifact profile does not match the requested profile")
    _check_completeness(
        profile_id=profile_id,
        profile_version=profile_version,
        required_preserves=required,
        available_preserves=metadata["preserves"],
    )


def validate_metrics_artifact_for_consumer(
    artifact: Mapping[str, Any],
    *,
    profile_id: str,
    profile_version: int,
    required_preserves: object,
) -> None:
    """Strictly validate one exact metrics profile and its capabilities."""
    required = _required_capabilities(required_preserves)
    artifact_kind = select_metrics_profile(profile_id, profile_version)
    if artifact_kind == "metrics":
        validate_metrics_source_v1(artifact)
        if artifact.get("schema_version") != 1 or artifact.get("metrics_semantics_version") != 4:
            raise ValueError("metrics.full v1 requires Metrics DTO schema 1 / semantics 4")
        return
    metadata = metrics_profile_metadata(profile_id, profile_version)
    validate_metrics_view_v1(artifact)
    if artifact["profile"] != {"id": profile_id, "version": profile_version}:
        raise ValueError("Metrics artifact profile does not match the requested profile")
    _check_completeness(
        profile_id=profile_id,
        profile_version=profile_version,
        required_preserves=required,
        available_preserves=metadata["preserves"],
    )


def validate_sibling_artifacts(
    graph_artifact: Mapping[str, Any],
    metrics_artifact: Mapping[str, Any],
    *,
    graph_profile_id: str,
    graph_profile_version: int,
    graph_required_preserves: object,
    metrics_profile_id: str,
    metrics_profile_version: int,
    metrics_required_preserves: object,
) -> str:
    """Validate exact sibling artifacts and their shared canonical graph identity."""
    validate_graph_artifact_for_consumer(
        graph_artifact,
        profile_id=graph_profile_id,
        profile_version=graph_profile_version,
        required_preserves=graph_required_preserves,
    )
    validate_metrics_artifact_for_consumer(
        metrics_artifact,
        profile_id=metrics_profile_id,
        profile_version=metrics_profile_version,
        required_preserves=metrics_required_preserves,
    )
    graph_kind = select_graph_profile(graph_profile_id, graph_profile_version)
    graph_fingerprint = (
        graph_artifact["project"]["fingerprint"]
        if graph_kind == "canonical"
        else graph_artifact["source"]["graph_fingerprint"]
    )
    metrics_kind = select_metrics_profile(metrics_profile_id, metrics_profile_version)
    metrics_graph_fingerprint = (
        metrics_artifact["input"]["graph_fingerprint"]
        if metrics_kind == "metrics"
        else metrics_artifact["source"]["graph_fingerprint"]
    )
    if graph_fingerprint != metrics_graph_fingerprint:
        raise ValueError("Graph and metrics artifacts have different source graph fingerprints")
    return graph_fingerprint


__all__ = [
    "ProfileCompletenessError",
    "validate_graph_artifact_for_consumer",
    "validate_metrics_artifact_for_consumer",
    "validate_sibling_artifacts",
]
