"""Synchronous dependency ports for Parser Service application logic."""

from contextlib import AbstractContextManager
from datetime import datetime
from pathlib import Path
from typing import Callable, Mapping, Protocol, TypeAlias

from ..contracts import EventEnvelope
from .models import ArtifactDescriptor, ClaimResult, DeliveryContext, DeliveryDecision, ProcessingRecord

DeliveryHandler: TypeAlias = Callable[[Mapping[str, object], DeliveryContext], DeliveryDecision]


class EventPublisher(Protocol):
    def publish(self, event: EventEnvelope) -> None: ...


class InputSignalSource(Protocol):
    def start(self, handler: DeliveryHandler) -> None: ...
    def stop(self) -> None: ...


class IdempotencyStore(Protocol):
    def claim(self, key: str, payload_digest: str, claim_token: str, lease_expires_at: datetime) -> ClaimResult: ...
    def load(self, key: str) -> ProcessingRecord | None: ...
    def record_saved(self, key: str, claim_token: str, event: EventEnvelope) -> ProcessingRecord: ...
    def record_failure(self, key: str, claim_token: str, event: EventEnvelope) -> ProcessingRecord: ...
    def record_published(self, key: str, claim_token: str) -> ProcessingRecord: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class EventIdGenerator(Protocol):
    def new_event_id(self) -> str: ...


class SourceResolver(Protocol):
    def materialize(self, source_uri: str) -> AbstractContextManager[Path]: ...


class GraphStagingArea(Protocol):
    def create_target(self, artifact_key: str) -> AbstractContextManager[Path]: ...


class GraphArtifactStore(Protocol):
    def save(self, staged_path: Path, artifact_key: str) -> ArtifactDescriptor: ...


class ParserGateway(Protocol):
    def parse(self, source_path: Path, output_path: Path) -> Path: ...
