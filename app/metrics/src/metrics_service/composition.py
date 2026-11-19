"""Dependency-injected local Metrics Service composition."""

from dataclasses import dataclass
from pathlib import Path

from .adapters.canonical_core import CanonicalArtifactValidator, CanonicalMetricsGateway
from .adapters.filesystem import LocalGraphInputResolver, LocalMetricsArtifactStore, LocalMetricsStagingArea
from .adapters.runtime import UUIDEventIdGenerator, UtcClock
from .adapters.sqlite_idempotency import SQLiteIdempotencyStore
from .application.handler import HandlerConfig, MetricsHandler
from .application.ports import Clock, EventIdGenerator, EventPublisher, InputSignalSource
from .contracts import Producer
from .runtime import RuntimeObserver, ServiceRuntime


@dataclass(frozen=True)
class LocalSettings:
    graph_root: Path
    staging_root: Path
    artifact_root: Path
    idempotency_database: Path
    producer_version: str
    sqlite_busy_timeout_ms: int = 5000


def build_application(settings: LocalSettings, *, publisher: EventPublisher,
                      clock: Clock | None = None,
                      ids: EventIdGenerator | None = None) -> MetricsHandler:
    actual_clock = clock or UtcClock()
    return MetricsHandler(
        config=HandlerConfig(Producer("metrics-service", settings.producer_version)),
        clock=actual_clock, ids=ids or UUIDEventIdGenerator(), publisher=publisher,
        idempotency=SQLiteIdempotencyStore(settings.idempotency_database,
                                           now=actual_clock.now,
                                           busy_timeout_ms=settings.sqlite_busy_timeout_ms),
        graphs=LocalGraphInputResolver(settings.graph_root),
        staging=LocalMetricsStagingArea(settings.staging_root),
        artifacts=LocalMetricsArtifactStore(settings.artifact_root),
        metrics=CanonicalMetricsGateway(), validator=CanonicalArtifactValidator(),
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
