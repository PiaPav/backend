import json
from pathlib import Path

from metrics_service.adapters.runtime import ManualInputSignalSource as MetricsSource
from metrics_service.adapters.runtime import RecordingEventPublisher as MetricsPublisher
from metrics_service.application.models import DeliveryContext as MetricsContext
from metrics_service.application.models import DeliveryDecision as MetricsDecision
from metrics_service.composition import LocalSettings as MetricsSettings
from metrics_service.composition import build_runtime as build_metrics_runtime
from parser_service.adapters.runtime import ManualInputSignalSource as ParserSource
from parser_service.adapters.runtime import RecordingEventPublisher as ParserPublisher
from parser_service.application.models import DeliveryContext as ParserContext
from parser_service.application.models import DeliveryDecision as ParserDecision
from parser_service.composition import LocalSettings as ParserSettings
from parser_service.composition import build_runtime as build_parser_runtime
from parser_service.contracts import EventEnvelope, ParserStart, Producer, RequestedGraph
from parser_service.contracts import encode_json as encode_parser_json


def test_local_parser_to_metrics_choreography_crosses_json_wire_boundary(tmp_path: Path) -> None:
    projects, project = tmp_path / "projects", tmp_path / "projects" / "tiny"
    project.mkdir(parents=True)
    (project / "module.py").write_text(
        "def helper(value):\n    return value + 1\n\ndef run():\n    return helper(1)\n",
        encoding="utf-8",
    )
    parser_stage, graph_artifacts = tmp_path / "parser-stage", tmp_path / "graphs"
    metrics_stage, metrics_artifacts = tmp_path / "metrics-stage", tmp_path / "metrics"
    for directory in (parser_stage, graph_artifacts, metrics_stage, metrics_artifacts):
        directory.mkdir()

    command = EventEnvelope(
        "parser-input", "parser.start.v1", 1, "2026-01-02T03:04:05Z",
        "workflow-correlation", "request", "tenant", Producer("integration-test", "1"),
        ParserStart(project.as_uri(), RequestedGraph(1, 7)),
    )
    parser_source, parser_publisher = ParserSource(), ParserPublisher()
    parser_runtime = build_parser_runtime(
        ParserSettings(projects, parser_stage, graph_artifacts, tmp_path / "parser.sqlite", "test"),
        source=parser_source, publisher=parser_publisher,
    )
    parser_runtime.start()
    command_wire = json.loads(encode_parser_json(command).decode("utf-8"))
    assert parser_source.deliver(command_wire, ParserContext("tenant")) is ParserDecision.ACK
    assert parser_source.deliver(command_wire, ParserContext("tenant")) is ParserDecision.ACK
    assert len(parser_publisher.events) == 1
    graph_ready = parser_publisher.events[0]
    parser_runtime.stop()

    # Only JSON-compatible data crosses the service boundary; no Parser DTO is passed.
    graph_wire = json.loads(encode_parser_json(graph_ready).decode("utf-8"))
    metrics_source, metrics_publisher = MetricsSource(), MetricsPublisher()
    metrics_runtime = build_metrics_runtime(
        MetricsSettings(graph_artifacts, metrics_stage, metrics_artifacts, tmp_path / "metrics.sqlite", "test"),
        source=metrics_source, publisher=metrics_publisher,
    )
    metrics_runtime.start()
    assert metrics_source.deliver(graph_wire, MetricsContext("tenant")) is MetricsDecision.ACK
    assert metrics_source.deliver(json.loads(json.dumps(graph_wire)), MetricsContext("tenant")) is MetricsDecision.ACK
    assert len(metrics_publisher.events) == 1
    metrics_ready = metrics_publisher.events[0]
    metrics_runtime.stop()

    assert graph_ready.correlation_id == metrics_ready.correlation_id == command.correlation_id
    assert graph_ready.causation_id == command.event_id
    assert metrics_ready.causation_id == graph_ready.event_id
    assert graph_ready.tenant_id == metrics_ready.tenant_id == command.tenant_id
    assert metrics_ready.payload.graph.graph_fingerprint == graph_ready.payload.graph.graph_fingerprint
    assert metrics_ready.payload.graph.uri == graph_ready.payload.graph.uri
    assert not any(parser_stage.iterdir())
    assert not any(metrics_stage.iterdir())
