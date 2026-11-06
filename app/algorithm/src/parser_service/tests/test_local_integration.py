import hashlib
import json
from pathlib import Path

import graph_dto

from parser_service.adapters import canonical_core
from parser_service.adapters.runtime import ManualInputSignalSource, RecordingEventPublisher
from parser_service.application.models import DeliveryContext, DeliveryDecision
from parser_service.composition import LocalSettings, build_runtime
from parser_service.contracts import EventEnvelope, ParserStart, Producer, RequestedGraph, to_mapping


class _FailingCapturePublisher:
    def __init__(self) -> None:
        self.attempts = []

    def publish(self, event: EventEnvelope) -> None:
        self.attempts.append(event)
        raise OSError("controlled publish outage")


def _command(project: Path) -> EventEnvelope:
    return EventEnvelope(
        "parser-input", "parser.start.v1", 1, "2026-01-02T03:04:05Z",
        "correlation", "request", "tenant", Producer("integration-test", "1"),
        ParserStart(project.as_uri(), RequestedGraph(1, 7)),
    )


def _settings(tmp_path: Path, project_root: Path) -> LocalSettings:
    staging, artifacts = tmp_path / "parser-stage", tmp_path / "parser-artifacts"
    staging.mkdir(exist_ok=True)
    artifacts.mkdir(exist_ok=True)
    return LocalSettings(project_root, staging, artifacts, tmp_path / "parser.sqlite", "test")


def test_local_parser_runtime_persists_canonical_graph_and_replays_after_restart(
    tmp_path: Path, monkeypatch,
) -> None:
    projects, project = tmp_path / "projects", tmp_path / "projects" / "tiny"
    project.mkdir(parents=True)
    (project / "sample.py").write_text("def answer():\n    return 42\n", encoding="utf-8")
    settings = _settings(tmp_path, projects)
    command, wire = _command(project), to_mapping(_command(project))
    context = DeliveryContext("tenant")

    calls = 0
    real_parse = canonical_core.parser.parse_project

    def counted_parse(source: Path, output: Path) -> Path:
        nonlocal calls
        calls += 1
        return real_parse(source, output)

    monkeypatch.setattr(canonical_core.parser, "parse_project", counted_parse)
    failing, first_source = _FailingCapturePublisher(), ManualInputSignalSource()
    first_runtime = build_runtime(settings, source=first_source, publisher=failing)
    first_runtime.start()
    assert first_source.deliver(wire, context) is DeliveryDecision.RETRY
    first_runtime.stop()
    assert calls == 1
    persisted_event = failing.attempts[0]
    assert persisted_event.event_type == "graph.ready.v1"

    publisher, replay_source = RecordingEventPublisher(), ManualInputSignalSource()
    replay_runtime = build_runtime(settings, source=replay_source, publisher=publisher)
    replay_runtime.start()
    assert replay_source.deliver(wire, context) is DeliveryDecision.ACK
    assert publisher.events == (persisted_event,)
    assert calls == 1

    ready = publisher.events[0]
    descriptor = ready.payload.graph
    artifact = next((settings.artifact_root / "graph").glob("*.json"))
    raw = artifact.read_bytes()
    graph = json.loads(raw)
    graph_dto.validate_graph_v1(graph)
    assert descriptor.uri == artifact.as_uri()
    assert descriptor.size_bytes == len(raw)
    assert descriptor.sha256 == hashlib.sha256(raw).hexdigest()
    assert descriptor.schema_version == graph["schema_version"] == 1
    assert descriptor.parser_semantics_version == graph["parser_semantics_version"] == 7
    assert descriptor.graph_fingerprint == graph_dto.graph_fingerprint(graph)
    assert (ready.correlation_id, ready.causation_id, ready.tenant_id) == (
        command.correlation_id, command.event_id, command.tenant_id,
    )
    assert not any(settings.staging_root.iterdir())

    assert replay_source.deliver(wire, context) is DeliveryDecision.ACK
    assert publisher.events == (persisted_event,)
    assert calls == 1
    replay_runtime.stop()
