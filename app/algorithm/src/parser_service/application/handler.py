"""Parser Service application handler for canonical graph artifacts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta, timezone
from typing import Mapping

from ..contracts import EventEnvelope, Failure, GraphDescriptor, GraphReady, Producer, from_mapping, to_mapping
from .errors import ApplicationError, ArtifactConflictError, ErrorDisposition, IdempotencyPayloadConflictError
from .models import ClaimDisposition, DeliveryContext, DeliveryDecision, ProcessingState
from .ports import Clock, EventIdGenerator, EventPublisher, GraphArtifactStore, GraphStagingArea, GraphValidator, IdempotencyStore, ParserGateway, SourceResolver


@dataclass(frozen=True)
class HandlerConfig:
    producer: Producer
    lease_duration: timedelta = timedelta(minutes=5)


class ParserHandler:
    def __init__(self, *, config: HandlerConfig, clock: Clock, ids: EventIdGenerator,
                 publisher: EventPublisher, idempotency: IdempotencyStore,
                 sources: SourceResolver, staging: GraphStagingArea,
                 artifacts: GraphArtifactStore, parser: ParserGateway,
                 validator: GraphValidator) -> None:
        self._config, self._clock, self._ids = config, clock, ids
        self._publisher, self._idempotency = publisher, idempotency
        self._sources, self._staging, self._artifacts = sources, staging, artifacts
        self._parser, self._validator = parser, validator

    def __call__(self, wire: Mapping[str, object], context: DeliveryContext) -> DeliveryDecision:
        try:
            event = from_mapping(wire)
            if event.event_type != "parser.start.v1" or event.schema_version != 1:
                return DeliveryDecision.REJECT
            if event.tenant_id != context.authorized_tenant_id:
                return DeliveryDecision.REJECT
        except (TypeError, ValueError):
            return DeliveryDecision.REJECT
        except Exception:
            return DeliveryDecision.RETRY
        try:
            canonical = json.dumps(to_mapping(event), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
            digest = hashlib.sha256(canonical).hexdigest()
            key = "parser:" + hashlib.sha256(f"parser\0{event.tenant_id}\0{event.event_id}".encode()).hexdigest()
        except Exception:
            return DeliveryDecision.RETRY
        try:
            token = self._ids.new_event_id()
            claimed = self._idempotency.claim(key, digest, token, self._clock.now() + self._config.lease_duration)
        except IdempotencyPayloadConflictError:
            return DeliveryDecision.REJECT
        except ApplicationError as error:
            return self._decision(error)
        except Exception:
            return DeliveryDecision.RETRY
        try:
            if claimed.record.payload_digest != digest:
                return DeliveryDecision.REJECT
            if claimed.disposition is ClaimDisposition.BUSY:
                return DeliveryDecision.RETRY
            if claimed.disposition is ClaimDisposition.EXISTING:
                if claimed.record.state in {ProcessingState.PUBLISHED, ProcessingState.FAILED_PUBLISHED}:
                    return DeliveryDecision.ACK
                self._publisher.publish(claimed.record.output_event)  # type: ignore[arg-type]
                self._idempotency.record_published(key, claimed.record.claim_token)
                return DeliveryDecision.ACK
        except Exception:
            return DeliveryDecision.RETRY
        try:
            artifact_key = "graph/" + hashlib.sha256(f"{event.tenant_id}\0{event.event_id}\0{digest}".encode()).hexdigest()
            with self._sources.materialize(event.payload.source_uri) as source, self._staging.create_target(artifact_key) as target:
                output = self._parser.parse(source, target)
                fingerprint = self._validator.validate(output)
                artifact_bytes = output.read_bytes()
                descriptor = self._artifacts.save(output, artifact_key)
                if (descriptor.size_bytes != len(artifact_bytes)
                        or descriptor.sha256 != hashlib.sha256(artifact_bytes).hexdigest()):
                    raise ArtifactConflictError("Stored graph descriptor does not match canonical content")
            ready = self._envelope(event, "graph.ready.v1", GraphReady(event.payload.source_uri, GraphDescriptor(
                descriptor.uri, descriptor.sha256, descriptor.size_bytes, 1, 7, fingerprint)))
        except ApplicationError as error:
            if error.disposition is not ErrorDisposition.FAILURE:
                return self._decision(error)
            return self._persist_failure(key, token, event, error)
        except Exception:
            return DeliveryDecision.RETRY
        try:
            self._idempotency.record_saved(key, token, ready)
        except Exception:
            return DeliveryDecision.RETRY
        try:
            self._publisher.publish(ready)
            self._idempotency.record_published(key, token)
            return DeliveryDecision.ACK
        except Exception:
            return DeliveryDecision.RETRY

    def _envelope(self, source: EventEnvelope, event_type: str, payload: object) -> EventEnvelope:
        occurred_at = self._clock.now().astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        return EventEnvelope(self._ids.new_event_id(), event_type, 1, occurred_at,
                             source.correlation_id, source.event_id, source.tenant_id, self._config.producer, payload)

    def _persist_failure(self, key: str, token: str, source: EventEnvelope, error: ApplicationError) -> DeliveryDecision:
        try:
            failure = self._envelope(source, "parser.failed.v1", Failure("parser", source.event_id, error.error_code, error.safe_message, False))
            self._idempotency.record_failure(key, token, failure)
            self._publisher.publish(failure)
            self._idempotency.record_published(key, token)
            return DeliveryDecision.ACK
        except Exception:
            return DeliveryDecision.RETRY

    @staticmethod
    def _decision(error: ApplicationError) -> DeliveryDecision:
        if error.disposition is ErrorDisposition.REJECT:
            return DeliveryDecision.REJECT
        if error.disposition is ErrorDisposition.FAILURE:
            return DeliveryDecision.ACK
        return DeliveryDecision.RETRY


__all__ = ["HandlerConfig", "ParserHandler"]
