from datetime import timezone

import pytest

import parser_service.composition as composition
from parser_service.adapters.runtime import ManualInputSignalSource, RecordingEventPublisher, UUIDEventIdGenerator, UtcClock
from parser_service.application.handler import ParserHandler
from parser_service.composition import LocalSettings, build_application, build_runtime
from parser_service.runtime import RuntimeState


def test_system_and_recording_adapters() -> None:
    clock = UtcClock()
    assert clock.now().utcoffset() == timezone.utc.utcoffset(clock.now())
    assert UUIDEventIdGenerator().new_event_id() != UUIDEventIdGenerator().new_event_id()
    publisher = RecordingEventPublisher()
    first, second = object(), object()
    publisher.publish(first)  # type: ignore[arg-type]
    publisher.publish(second)  # type: ignore[arg-type]
    assert publisher.events == (first, second)
    publisher.fail_with(RuntimeError("controlled"))
    with pytest.raises(RuntimeError, match="controlled"):
        publisher.publish(first)  # type: ignore[arg-type]


def test_local_composition_keeps_transport_dependencies_injected(tmp_path) -> None:
    source_root, staging, artifacts = tmp_path / "sources", tmp_path / "stage", tmp_path / "artifacts"
    source_root.mkdir(); staging.mkdir(); artifacts.mkdir()
    settings = LocalSettings(source_root, staging, artifacts, tmp_path / "state.sqlite", "1")
    publisher, source = RecordingEventPublisher(), ManualInputSignalSource()
    assert isinstance(build_application(settings, publisher=publisher), ParserHandler)
    runtime = build_runtime(settings, source=source, publisher=publisher)
    assert runtime.state is RuntimeState.CREATED


def test_local_composition_uses_hyphenated_producer_identity(tmp_path, monkeypatch) -> None:
    source_root, staging, artifacts = tmp_path / "sources", tmp_path / "stage", tmp_path / "artifacts"
    source_root.mkdir(); staging.mkdir(); artifacts.mkdir()
    settings = LocalSettings(source_root, staging, artifacts, tmp_path / "state.sqlite", "1")
    captured = {}

    def capture_handler(**dependencies):
        captured.update(dependencies)
        return object()

    monkeypatch.setattr(composition, "ParserHandler", capture_handler)
    build_application(settings, publisher=RecordingEventPublisher())

    assert captured["config"].producer.service == "parser-service"
