"""Metrics Service application handler for canonical artifacts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta, timezone
from typing import Mapping

from ..contracts import EventEnvelope, Failure, GraphReference, MetricsDescriptor, MetricsReady, Producer, from_mapping, to_mapping
from .errors import (ApplicationError, ArtifactConflictError, ErrorDisposition, GraphChecksumMismatchError,
                     GraphFingerprintMismatchError, IdempotencyPayloadConflictError)
from .models import ClaimDisposition, DeliveryContext, DeliveryDecision, ProcessingState
from .ports import CanonicalValidator, Clock, EventIdGenerator, EventPublisher, GraphInputResolver, IdempotencyStore, MetricsArtifactStore, MetricsGateway, MetricsStagingArea


@dataclass(frozen=True)
class HandlerConfig:
    producer: Producer
    lease_duration: timedelta = timedelta(minutes=5)


class MetricsHandler:
    def __init__(self, *, config: HandlerConfig, clock: Clock, ids: EventIdGenerator,
                 publisher: EventPublisher, idempotency: IdempotencyStore,
                 graphs: GraphInputResolver, staging: MetricsStagingArea,
                 artifacts: MetricsArtifactStore, metrics: MetricsGateway,
                 validator: CanonicalValidator) -> None:
        self._config, self._clock, self._ids = config, clock, ids
        self._publisher, self._idempotency = publisher, idempotency
        self._graphs, self._staging, self._artifacts = graphs, staging, artifacts
        self._metrics, self._validator = metrics, validator

    def __call__(self, wire: Mapping[str, object], context: DeliveryContext) -> DeliveryDecision:
        try:
            event = from_mapping(wire)
            if event.event_type != "graph.ready.v1" or event.schema_version != 1:
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
            key = "metrics:" + hashlib.sha256(f"metrics\0{event.tenant_id}\0{event.event_id}".encode()).hexdigest()
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
            graph = event.payload.graph
            artifact_key = "metrics/" + hashlib.sha256(f"{event.tenant_id}\0{event.event_id}\0{digest}".encode()).hexdigest()
            with self._graphs.materialize(graph.uri) as graph_path:
                raw = graph_path.read_bytes()
                if len(raw) != graph.size_bytes or hashlib.sha256(raw).hexdigest() != graph.sha256:
                    raise GraphChecksumMismatchError("Graph artifact does not match its descriptor")
                fingerprint = self._validator.validate_graph(graph_path)
                if fingerprint != graph.graph_fingerprint:
                    raise GraphFingerprintMismatchError("Graph fingerprint does not match its descriptor")
                with self._staging.create_target(artifact_key) as target:
                    output = self._metrics.calculate(graph_path, target)
                    self._validator.validate_metrics(output, fingerprint)
                    artifact_bytes = output.read_bytes()
                    descriptor = self._artifacts.save(output, artifact_key)
                    if (descriptor.size_bytes != len(artifact_bytes)
                            or descriptor.sha256 != hashlib.sha256(artifact_bytes).hexdigest()):
                        raise ArtifactConflictError("Stored metrics descriptor does not match canonical content")
            ready = self._envelope(event, "metrics.ready.v1", MetricsReady(
                GraphReference(graph.uri, fingerprint), MetricsDescriptor(
                    descriptor.uri, descriptor.sha256, descriptor.size_bytes, 1, 4)))
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
            failure = self._envelope(source, "metrics.failed.v1", Failure("metrics", source.event_id, error.error_code, error.safe_message, False))
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


__all__ = ["HandlerConfig", "MetricsHandler"]
