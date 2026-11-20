"""Transport-neutral application handler for the LLM harness."""

from __future__ import annotations

import hashlib
import json
import re
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Mapping, Protocol

from harness_service.harness_runner import HarnessRequest, HarnessRunner

_SHA256 = re.compile(r"[0-9a-f]{64}")
_RFC3339_UTC = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z")
_ENVELOPE_FIELDS = {
    "event_id", "event_type", "schema_version", "occurred_at",
    "correlation_id", "causation_id", "tenant_id", "producer", "payload",
}


class DeliveryDecision(StrEnum):
    ACK = "ack"
    RETRY = "retry"
    REJECT = "reject"


@dataclass(frozen=True, slots=True)
class DeliveryContext:
    """Trusted information supplied by the transport adapter."""

    authorized_tenant_id: str

    def __post_init__(self) -> None:
        _nonempty(self.authorized_tenant_id, "authorized_tenant_id")


@dataclass(frozen=True, slots=True)
class Producer:
    service: str
    version: str

    def __post_init__(self) -> None:
        _nonempty(self.service, "producer.service")
        _nonempty(self.version, "producer.version")


@dataclass(frozen=True, slots=True)
class ArtifactDescriptor:
    """Descriptor used for the harness result artifact."""

    uri: str
    sha256: str
    size_bytes: int
    schema_version: int

    def __post_init__(self) -> None:
        _artifact_fields(self.uri, self.sha256, self.size_bytes, self.schema_version, "result")


@dataclass(frozen=True, slots=True)
class GraphDescriptor:
    uri: str
    sha256: str
    size_bytes: int
    schema_version: int
    parser_semantics_version: int
    graph_fingerprint: str

    def __post_init__(self) -> None:
        _artifact_fields(self.uri, self.sha256, self.size_bytes, self.schema_version, "graph")
        if self.parser_semantics_version != 7:
            raise InvalidEventError("graph.parser_semantics_version must be 7")
        _digest(self.graph_fingerprint, "graph.graph_fingerprint")


@dataclass(frozen=True, slots=True)
class MetricsDescriptor:
    uri: str
    sha256: str
    size_bytes: int
    schema_version: int
    metrics_semantics_version: int
    graph_fingerprint: str

    def __post_init__(self) -> None:
        _artifact_fields(self.uri, self.sha256, self.size_bytes, self.schema_version, "metrics")
        if self.metrics_semantics_version != 4:
            raise InvalidEventError("metrics.metrics_semantics_version must be 4")
        _digest(self.graph_fingerprint, "metrics.graph_fingerprint")


@dataclass(frozen=True, slots=True)
class SourceIndexDescriptor:
    uri: str
    sha256: str
    size_bytes: int
    schema_version: int
    project_fingerprint: str

    def __post_init__(self) -> None:
        _artifact_fields(self.uri, self.sha256, self.size_bytes, self.schema_version, "source_index")
        _digest(self.project_fingerprint, "source_index.project_fingerprint")


@dataclass(frozen=True, slots=True)
class HarnessStart:
    event_id: str
    occurred_at: str
    correlation_id: str
    causation_id: str
    tenant_id: str
    producer: Producer
    source_uri: str
    graph: GraphDescriptor
    metrics: MetricsDescriptor
    source_index: SourceIndexDescriptor


@dataclass(frozen=True, slots=True)
class MaterializedInputs:
    graph_path: Path
    metrics_path: Path
    source_index_path: Path


class InputMaterializer(Protocol):
    """Materialize and validate one immutable analysis snapshot.

    The implementation must materialize ``source_uri`` and all three JSON
    artifacts, verify their declared sizes/SHA-256 values and DTO versions,
    verify the graph/metrics fingerprints, then rewrite
    ``source_index.project.root`` to the local materialized source root.  The
    returned source-index path must remain valid for GetContent/GetStructure
    until the context manager exits.
    """

    def materialize(
        self, *, source_uri: str, graph: GraphDescriptor, metrics: MetricsDescriptor,
        source_index: SourceIndexDescriptor,
    ) -> AbstractContextManager[MaterializedInputs]: ...


class ResultStore(Protocol):
    async def save(self, *, tenant_id: str, event_id: str, content: str) -> ArtifactDescriptor: ...


class EventPublisher(Protocol):
    """Must return only after publisher confirmation."""

    async def publish(self, event: Mapping[str, object]) -> None: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class UtcClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class ClaimDisposition(StrEnum):
    NEW = "new"
    BUSY = "busy"
    SAVED = "saved"
    PUBLISHED = "published"


@dataclass(frozen=True, slots=True)
class Claim:
    disposition: ClaimDisposition
    claim_token: str
    output_event: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        if type(self.disposition) is not ClaimDisposition:
            raise TypeError("disposition must be a ClaimDisposition")
        _nonempty(self.claim_token, "claim_token")
        if self.disposition is ClaimDisposition.SAVED and self.output_event is None:
            raise ValueError("SAVED claim requires output_event")
        if self.disposition is not ClaimDisposition.SAVED and self.output_event is not None:
            raise ValueError("only SAVED claim may contain output_event")


class IdempotencyStore(Protocol):
    async def claim(self, *, key: str, payload_digest: str) -> Claim: ...
    async def save_output(self, *, key: str, claim_token: str,
                          output_event: Mapping[str, object]) -> None: ...
    async def mark_published(self, *, key: str, claim_token: str) -> None: ...


class InvalidEventError(ValueError):
    """The delivery violates the public contract and must not be retried."""


class RejectedInputError(RuntimeError):
    """A materialized artifact is permanently invalid."""


class PayloadConflictError(RuntimeError):
    """The same tenant/event ID was previously used with another payload."""


class HarnessHandler:
    EXPECTED_EVENT_TYPE = "harness.start.v1"
    EXPECTED_SCHEMA_VERSION = 1

    def __init__(
        self, *, runner: HarnessRunner, materializer: InputMaterializer,
        result_store: ResultStore, idempotency: IdempotencyStore,
        publisher: EventPublisher, producer: Producer | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._runner = runner
        self._materializer = materializer
        self._result_store = result_store
        self._idempotency = idempotency
        self._publisher = publisher
        self._producer = producer or Producer("harness-service", "1")
        self._clock = clock or UtcClock()

    async def handle(self, wire: Mapping[str, object],
                     context: DeliveryContext) -> DeliveryDecision:
        try:
            event = self._parse_event(wire)
            if event.tenant_id != context.authorized_tenant_id:
                return DeliveryDecision.REJECT
            payload_digest = self._payload_digest(wire)
            key = "harness:" + hashlib.sha256(
                f"harness\0{event.tenant_id}\0{event.event_id}".encode("utf-8")
            ).hexdigest()
            claim = await self._idempotency.claim(key=key, payload_digest=payload_digest)
        except (InvalidEventError, PayloadConflictError):
            return DeliveryDecision.REJECT
        except Exception:
            return DeliveryDecision.RETRY

        if claim.disposition is ClaimDisposition.PUBLISHED:
            return DeliveryDecision.ACK
        if claim.disposition is ClaimDisposition.BUSY:
            return DeliveryDecision.RETRY
        if claim.disposition is ClaimDisposition.SAVED:
            return await self._republish_saved(key, claim)

        try:
            with self._materializer.materialize(
                source_uri=event.source_uri, graph=event.graph, metrics=event.metrics,
                source_index=event.source_index,
            ) as inputs:
                result = await self._runner.execute(HarnessRequest(
                    tenant_id=event.tenant_id,
                    event_id=event.event_id,
                    graph_path=inputs.graph_path,
                    metrics_path=inputs.metrics_path,
                    source_index_path=inputs.source_index_path,
                ))
            descriptor = await self._result_store.save(
                tenant_id=event.tenant_id, event_id=event.event_id,
                content=result.content,
            )
            output_event = self._make_completed_event(event, descriptor)
            await self._idempotency.save_output(
                key=key, claim_token=claim.claim_token,
                output_event=output_event,
            )
        except RejectedInputError:
            return DeliveryDecision.REJECT
        except Exception:
            return DeliveryDecision.RETRY

        try:
            await self._publisher.publish(output_event)
            await self._idempotency.mark_published(
                key=key, claim_token=claim.claim_token,
            )
            return DeliveryDecision.ACK
        except Exception:
            return DeliveryDecision.RETRY

    async def _republish_saved(self, key: str, claim: Claim) -> DeliveryDecision:
        try:
            await self._publisher.publish(claim.output_event)  # type: ignore[arg-type]
            await self._idempotency.mark_published(
                key=key, claim_token=claim.claim_token,
            )
            return DeliveryDecision.ACK
        except Exception:
            return DeliveryDecision.RETRY

    def _parse_event(self, wire: Mapping[str, object]) -> HarnessStart:
        _exact_keys(wire, _ENVELOPE_FIELDS, "envelope")
        if wire.get("event_type") != self.EXPECTED_EVENT_TYPE:
            raise InvalidEventError("unsupported event_type")
        if type(wire.get("schema_version")) is not int or wire["schema_version"] != 1:
            raise InvalidEventError("schema_version must be 1")

        producer_data = _mapping(wire.get("producer"), "producer")
        _exact_keys(producer_data, {"service", "version"}, "producer")
        payload = _mapping(wire.get("payload"), "payload")
        _exact_keys(payload, {"source_uri", "graph", "metrics", "source_index"}, "payload")

        graph = self._parse_graph(_mapping(payload["graph"], "graph"))
        metrics = self._parse_metrics(_mapping(payload["metrics"], "metrics"))
        source_index = self._parse_source_index(
            _mapping(payload["source_index"], "source_index")
        )
        if metrics.graph_fingerprint != graph.graph_fingerprint:
            raise InvalidEventError("metrics and graph fingerprints differ")
        occurred_at = _nonempty(wire.get("occurred_at"), "occurred_at")
        _utc_datetime(occurred_at)
        return HarnessStart(
            event_id=_nonempty(wire.get("event_id"), "event_id"),
            occurred_at=occurred_at,
            correlation_id=_nonempty(wire.get("correlation_id"), "correlation_id"),
            causation_id=_nonempty(wire.get("causation_id"), "causation_id"),
            tenant_id=_nonempty(wire.get("tenant_id"), "tenant_id"),
            producer=Producer(_nonempty(producer_data["service"], "producer.service"),
                              _nonempty(producer_data["version"], "producer.version")),
            source_uri=_nonempty(payload["source_uri"], "source_uri"),
            graph=graph, metrics=metrics, source_index=source_index,
        )

    @staticmethod
    def _parse_graph(data: Mapping[str, object]) -> GraphDescriptor:
        _exact_keys(data, {"uri", "sha256", "size_bytes", "schema_version",
                           "parser_semantics_version", "graph_fingerprint"}, "graph")
        return GraphDescriptor(
            _nonempty(data["uri"], "graph.uri"), _string(data["sha256"], "graph.sha256"),
            _integer(data["size_bytes"], "graph.size_bytes"),
            _integer(data["schema_version"], "graph.schema_version"),
            _integer(data["parser_semantics_version"], "graph.parser_semantics_version"),
            _string(data["graph_fingerprint"], "graph.graph_fingerprint"),
        )

    @staticmethod
    def _parse_metrics(data: Mapping[str, object]) -> MetricsDescriptor:
        _exact_keys(data, {"uri", "sha256", "size_bytes", "schema_version",
                           "metrics_semantics_version", "graph_fingerprint"}, "metrics")
        return MetricsDescriptor(
            _nonempty(data["uri"], "metrics.uri"), _string(data["sha256"], "metrics.sha256"),
            _integer(data["size_bytes"], "metrics.size_bytes"),
            _integer(data["schema_version"], "metrics.schema_version"),
            _integer(data["metrics_semantics_version"], "metrics.metrics_semantics_version"),
            _string(data["graph_fingerprint"], "metrics.graph_fingerprint"),
        )

    @staticmethod
    def _parse_source_index(data: Mapping[str, object]) -> SourceIndexDescriptor:
        _exact_keys(data, {"uri", "sha256", "size_bytes", "schema_version",
                           "project_fingerprint"}, "source_index")
        return SourceIndexDescriptor(
            _nonempty(data["uri"], "source_index.uri"),
            _string(data["sha256"], "source_index.sha256"),
            _integer(data["size_bytes"], "source_index.size_bytes"),
            _integer(data["schema_version"], "source_index.schema_version"),
            _string(data["project_fingerprint"], "source_index.project_fingerprint"),
        )

    @staticmethod
    def _payload_digest(wire: Mapping[str, object]) -> str:
        canonical = json.dumps(wire, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":"), allow_nan=False).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    def _make_completed_event(self, source: HarnessStart,
                              descriptor: ArtifactDescriptor) -> dict[str, object]:
        occurred_at = self._clock.now()
        if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime")
        timestamp = occurred_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        return {
            "event_id": f"{source.event_id}:harness-result",
            "event_type": "harness.completed.v1",
            "schema_version": 1,
            "occurred_at": timestamp,
            "correlation_id": source.correlation_id,
            "causation_id": source.event_id,
            "tenant_id": source.tenant_id,
            "producer": {"service": self._producer.service, "version": self._producer.version},
            "payload": {"result": {
                "uri": descriptor.uri, "sha256": descriptor.sha256,
                "size_bytes": descriptor.size_bytes,
                "schema_version": descriptor.schema_version,
            }},
        }


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise InvalidEventError(f"{name} must be an object with string keys")
    return value


def _exact_keys(value: Mapping[str, object], expected: set[str], name: str) -> None:
    actual = set(value)
    if actual != expected:
        raise InvalidEventError(
            f"{name} fields differ: missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        )


def _string(value: object, name: str) -> str:
    if type(value) is not str:
        raise InvalidEventError(f"{name} must be a string")
    return value


def _nonempty(value: object, name: str) -> str:
    result = _string(value, name)
    if not result or any(ord(character) < 32 for character in result):
        raise InvalidEventError(f"{name} must be a non-empty safe string")
    return result


def _integer(value: object, name: str) -> int:
    if type(value) is not int:
        raise InvalidEventError(f"{name} must be an integer")
    return value


def _digest(value: object, name: str) -> str:
    result = _string(value, name)
    if _SHA256.fullmatch(result) is None:
        raise InvalidEventError(f"{name} must be a lowercase SHA-256 value")
    return result


def _artifact_fields(uri: object, sha256: object, size_bytes: object,
                     schema_version: object, name: str) -> None:
    _nonempty(uri, f"{name}.uri")
    _digest(sha256, f"{name}.sha256")
    if type(size_bytes) is not int or size_bytes < 0:
        raise InvalidEventError(f"{name}.size_bytes must be a nonnegative integer")
    if type(schema_version) is not int or schema_version != 1:
        raise InvalidEventError(f"{name}.schema_version must be 1")


def _utc_datetime(value: str) -> None:
    if _RFC3339_UTC.fullmatch(value) is None:
        raise InvalidEventError("occurred_at must be UTC RFC 3339")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise InvalidEventError("occurred_at must be UTC RFC 3339") from error
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise InvalidEventError("occurred_at must be UTC RFC 3339")


__all__ = [
    "ArtifactDescriptor", "Claim", "ClaimDisposition", "Clock", "DeliveryContext",
    "DeliveryDecision", "EventPublisher", "GraphDescriptor", "HarnessHandler",
    "HarnessStart", "IdempotencyStore", "InputMaterializer", "InvalidEventError",
    "MaterializedInputs", "MetricsDescriptor", "PayloadConflictError", "Producer",
    "RejectedInputError", "ResultStore", "SourceIndexDescriptor", "UtcClock",
]
