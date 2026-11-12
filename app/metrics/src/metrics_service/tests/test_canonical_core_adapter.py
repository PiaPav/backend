from pathlib import Path

import pytest

from metrics_service.adapters import canonical_core
from metrics_service.application.errors import InvalidGraphDtoError, InvalidMetricsDtoError


def test_metrics_adapter_delegates_to_public_api(monkeypatch, tmp_path: Path) -> None:
    graph, output = tmp_path / "graph.json", tmp_path / "metrics.json"
    calls = []
    monkeypatch.setattr(canonical_core.metrics, "calculate_metrics", lambda left, right: calls.append((left, right)) or right)

    assert canonical_core.CanonicalMetricsGateway().calculate(graph, output) == output
    assert calls == [(graph, output)]


def test_metrics_validator_delegates_full_contract_validation(monkeypatch, tmp_path: Path) -> None:
    artifact = tmp_path / "metrics.json"
    artifact.write_text('{"input":{"graph_schema_version":1,"graph_fingerprint":"expected"}}', encoding="utf-8")
    calls = []
    monkeypatch.setattr(canonical_core.views, "validate_metrics_source_v1", lambda value: calls.append(value))

    canonical_core.CanonicalArtifactValidator().validate_metrics(artifact, "expected")

    assert calls == [{"input": {"graph_schema_version": 1, "graph_fingerprint": "expected"}}]


def test_metrics_validator_rejects_nested_contract_failure_safely(monkeypatch, tmp_path: Path) -> None:
    artifact = tmp_path / "metrics.json"
    artifact.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        canonical_core.views, "validate_metrics_source_v1",
        lambda value: (_ for _ in ()).throw(ValueError("sensitive nested detail")),
    )

    with pytest.raises(InvalidMetricsDtoError, match="^Canonical metrics validation failed$"):
        canonical_core.CanonicalArtifactValidator().validate_metrics(artifact, "expected")


def test_metrics_validator_requires_exact_input_linkage(monkeypatch, tmp_path: Path) -> None:
    artifact = tmp_path / "metrics.json"
    artifact.write_text(
        '{"input":{"graph_schema_version":1,"graph_fingerprint":"expected","extra":true}}', encoding="utf-8",
    )
    monkeypatch.setattr(canonical_core.views, "validate_metrics_source_v1", lambda value: None)

    with pytest.raises(InvalidMetricsDtoError, match="^Canonical metrics validation failed$"):
        canonical_core.CanonicalArtifactValidator().validate_metrics(artifact, "expected")


def test_metrics_graph_validator_translates_decode_error(tmp_path: Path) -> None:
    artifact = tmp_path / "graph.json"
    artifact.write_bytes(b"\xff")

    with pytest.raises(InvalidGraphDtoError, match="^Canonical graph validation failed$"):
        canonical_core.CanonicalArtifactValidator().validate_graph(artifact)
