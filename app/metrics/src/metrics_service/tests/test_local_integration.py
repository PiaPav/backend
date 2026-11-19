import hashlib
import json
from pathlib import Path

import graph_dto
import parser
import pytest

from metrics_service.adapters import canonical_core
from metrics_service.adapters.runtime import ManualInputSignalSource, RecordingEventPublisher
from metrics_service.application.models import DeliveryContext, DeliveryDecision
from metrics_service.composition import LocalSettings, build_runtime
from metrics_service.contracts import EventEnvelope, GraphDescriptor, GraphReady, Producer, to_mapping


class _FailingCapturePublisher:
    def __init__(self) -> None:
        self.attempts = []

    def publish(self, event: EventEnvelope) -> None:
        self.attempts.append(event)
        raise OSError("controlled publish outage")


def _graph(tmp_path: Path) -> tuple[Path, str]:
    source, graph = tmp_path / "source", tmp_path / "graphs" / "graph.json"
    source.mkdir()
    graph.parent.mkdir()
    (source / "sample.py").write_text("def square(value):\n    return value * value\n", encoding="utf-8")
    parser.parse_project(source, graph)
    value = json.loads(graph.read_bytes())
    graph_dto.validate_graph_v1(value)
    return graph, graph_dto.graph_fingerprint(value)


def _event(graph: Path, fingerprint: str, *, sha256: str | None = None) -> EventEnvelope:
    raw = graph.read_bytes()
    descriptor = GraphDescriptor(
        graph.as_uri(), sha256 or hashlib.sha256(raw).hexdigest(), len(raw), 1, 7, fingerprint,
    )
    return EventEnvelope(
        "graph-input", "graph.ready.v1", 1, "2026-01-02T03:04:05Z",
        "correlation", "parser-input", "tenant", Producer("parser-service", "test"),
        GraphReady((graph.parent / "source-placeholder").as_uri(), descriptor),
    )


def _settings(tmp_path: Path, graph_root: Path) -> LocalSettings:
    staging, artifacts = tmp_path / "metrics-stage", tmp_path / "metrics-artifacts"
    staging.mkdir(exist_ok=True)
    artifacts.mkdir(exist_ok=True)
    return LocalSettings(graph_root, staging, artifacts, tmp_path / "metrics.sqlite", "test")


def test_local_metrics_runtime_calculates_and_restart_replays_exact_event(
    tmp_path: Path, monkeypatch,
) -> None:
    graph, fingerprint = _graph(tmp_path)
    event, settings = _event(graph, fingerprint), _settings(tmp_path, graph.parent)
    wire, context = to_mapping(event), DeliveryContext("tenant")
    calls = 0
    real_calculate = canonical_core.metrics.calculate_metrics

    def counted_calculate(source: Path, output: Path) -> Path:
        nonlocal calls
        calls += 1
        return real_calculate(source, output)

    monkeypatch.setattr(canonical_core.metrics, "calculate_metrics", counted_calculate)
    failing, first_source = _FailingCapturePublisher(), ManualInputSignalSource()
    first = build_runtime(settings, source=first_source, publisher=failing)
    first.start()
    assert first_source.deliver(wire, context) is DeliveryDecision.RETRY
    first.stop()
    assert calls == 1
    persisted = failing.attempts[0]

    publisher, replay_source = RecordingEventPublisher(), ManualInputSignalSource()
    replay = build_runtime(settings, source=replay_source, publisher=publisher)
    replay.start()
    assert replay_source.deliver(wire, context) is DeliveryDecision.ACK
    assert publisher.events == (persisted,)
    assert calls == 1

    ready = publisher.events[0]
    descriptor = ready.payload.metrics
    artifact = next((settings.artifact_root / "metrics").glob("*.json"))
    raw, value = artifact.read_bytes(), json.loads(artifact.read_bytes())
    assert descriptor.uri == artifact.as_uri()
    assert descriptor.size_bytes == len(raw)
    assert descriptor.sha256 == hashlib.sha256(raw).hexdigest()
    assert (descriptor.schema_version, descriptor.metrics_semantics_version) == (1, 4)
    assert value["input"] == {"graph_schema_version": 1, "graph_fingerprint": fingerprint}
    assert ready.payload.graph.uri == graph.as_uri()
    assert ready.payload.graph.graph_fingerprint == fingerprint
    assert (ready.correlation_id, ready.causation_id, ready.tenant_id) == (
        event.correlation_id, event.event_id, event.tenant_id,
    )
    assert not any(settings.staging_root.iterdir())

    assert replay_source.deliver(wire, context) is DeliveryDecision.ACK
    assert publisher.events == (persisted,)
    assert calls == 1
    replay.stop()


@pytest.mark.parametrize("invalid", ["checksum", "fingerprint"])
def test_graph_integrity_is_rejected_before_metrics_core(tmp_path: Path, monkeypatch, invalid: str) -> None:
    graph, fingerprint = _graph(tmp_path)
    if invalid == "checksum":
        event = _event(graph, fingerprint, sha256="0" * 64)
    else:
        event = _event(graph, "0" * 64)
    calls = 0

    def unexpected_calculate(source: Path, output: Path) -> Path:
        nonlocal calls
        calls += 1
        return output

    monkeypatch.setattr(canonical_core.metrics, "calculate_metrics", unexpected_calculate)
    settings, source, publisher = _settings(tmp_path, graph.parent), ManualInputSignalSource(), RecordingEventPublisher()
    runtime = build_runtime(settings, source=source, publisher=publisher)
    runtime.start()
    assert source.deliver(to_mapping(event), DeliveryContext("tenant")) is DeliveryDecision.ACK
    runtime.stop()
    assert calls == 0
    assert publisher.events[0].event_type == "metrics.failed.v1"
