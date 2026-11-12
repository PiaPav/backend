from datetime import timezone

import pytest

import metrics_service.composition as composition
from metrics_service.adapters.runtime import ManualInputSignalSource, RecordingEventPublisher, UUIDEventIdGenerator, UtcClock
from metrics_service.application.handler import MetricsHandler
from metrics_service.composition import LocalSettings, build_application, build_runtime
from metrics_service.runtime import RuntimeState


def test_system_and_recording_adapters() -> None:
    now = UtcClock().now()
    assert now.utcoffset() == timezone.utc.utcoffset(now)
    ids = UUIDEventIdGenerator()
    assert ids.new_event_id() != ids.new_event_id()
    publisher = RecordingEventPublisher()
    event = object()
    publisher.publish(event)  # type: ignore[arg-type]
    assert publisher.events == (event,)
    publisher.fail_with(OSError("controlled"))
    with pytest.raises(OSError, match="controlled"):
        publisher.publish(event)  # type: ignore[arg-type]


def test_local_composition_keeps_transport_dependencies_injected(tmp_path) -> None:
    graphs, staging, artifacts = tmp_path / "graphs", tmp_path / "stage", tmp_path / "artifacts"
    graphs.mkdir(); staging.mkdir(); artifacts.mkdir()
    settings = LocalSettings(graphs, staging, artifacts, tmp_path / "state.sqlite", "1")
    publisher, source = RecordingEventPublisher(), ManualInputSignalSource()
    assert isinstance(build_application(settings, publisher=publisher), MetricsHandler)
    runtime = build_runtime(settings, source=source, publisher=publisher)
    assert runtime.state is RuntimeState.CREATED


def test_local_composition_uses_hyphenated_producer_identity(tmp_path, monkeypatch) -> None:
    graphs, staging, artifacts = tmp_path / "graphs", tmp_path / "stage", tmp_path / "artifacts"
    graphs.mkdir(); staging.mkdir(); artifacts.mkdir()
    settings = LocalSettings(graphs, staging, artifacts, tmp_path / "state.sqlite", "1")
    captured = {}

    def capture_handler(**dependencies):
        captured.update(dependencies)
        return object()

    monkeypatch.setattr(composition, "MetricsHandler", capture_handler)
    build_application(settings, publisher=RecordingEventPublisher())

    assert captured["config"].producer.service == "metrics-service"
