"""Dependency-injected local Parser Service composition."""

from dataclasses import dataclass
from pathlib import Path

from .adapters.canonical_core import CanonicalGraphValidator, CanonicalParserGateway
from .adapters.filesystem import LocalGraphArtifactStore, LocalGraphStagingArea, LocalSourceResolver
from .adapters.runtime import UUIDEventIdGenerator, UtcClock
from .adapters.sqlite_idempotency import SQLiteIdempotencyStore
from .application.handler import HandlerConfig, ParserHandler
from .application.ports import Clock, EventIdGenerator, EventPublisher, InputSignalSource
from .contracts import Producer
from .runtime import RuntimeObserver, ServiceRuntime


@dataclass(frozen=True)
class LocalSettings:
    source_root: Path
    staging_root: Path
    artifact_root: Path
    idempotency_database: Path
    producer_version: str
    sqlite_busy_timeout_ms: int = 5000


def build_application(settings: LocalSettings, *, publisher: EventPublisher,
                      clock: Clock | None = None,
                      ids: EventIdGenerator | None = None) -> ParserHandler:
    actual_clock = clock or UtcClock()
    return ParserHandler(
        config=HandlerConfig(Producer("parser-service", settings.producer_version)),
        clock=actual_clock, ids=ids or UUIDEventIdGenerator(), publisher=publisher,
        idempotency=SQLiteIdempotencyStore(settings.idempotency_database,
                                           now=actual_clock.now,
                                           busy_timeout_ms=settings.sqlite_busy_timeout_ms),
        sources=LocalSourceResolver(settings.source_root),
        staging=LocalGraphStagingArea(settings.staging_root),
        artifacts=LocalGraphArtifactStore(settings.artifact_root),
        parser=CanonicalParserGateway(), validator=CanonicalGraphValidator(),
    )


def build_runtime(settings: LocalSettings, *, source: InputSignalSource,
                  publisher: EventPublisher, observer: RuntimeObserver | None = None,
                  clock: Clock | None = None,
                  ids: EventIdGenerator | None = None) -> ServiceRuntime:
    return ServiceRuntime(source=source,
                          handler=build_application(settings, publisher=publisher,
                                                    clock=clock, ids=ids),
                          observer=observer)


__all__ = ["LocalSettings", "build_application", "build_runtime"]
