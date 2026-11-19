from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest

from parser_service.application import ArtifactDescriptor, ClaimDisposition, ClaimResult, DeliveryContext, DeliveryDecision, EventIdGenerator, ProcessingRecord, ProcessingState
from parser_service.contracts import EventEnvelope, Failure, GraphDescriptor, GraphReady, Producer

HASH = "a" * 64


def event(event_type="graph.ready.v1", retryable=False):
    payload = (GraphReady("file:///source", GraphDescriptor("file:///graph", HASH, 1, 1, 7, HASH))
               if event_type == "graph.ready.v1" else Failure("parser", "input", "failed", "safe", retryable))
    return EventEnvelope("output", event_type, 1, "2026-11-02T00:00:00Z", "correlation", "input", "tenant", Producer("parser-service", "1"), payload)


def claimed(**changes):
    values = dict(key="key", payload_digest=HASH, state=ProcessingState.CLAIMED, output_event=None,
                  claim_token="token", lease_expires_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    values.update(changes)
    return ProcessingRecord(**values)


def test_values_validation_and_frozen_models():
    assert {item.name: item.value for item in DeliveryDecision} == {"ACK": "ack", "RETRY": "retry", "REJECT": "reject"}
    assert {item.name: item.value for item in ProcessingState} == {
        "CLAIMED": "claimed", "SAVED": "saved", "PUBLISHED": "published",
        "FAILED_SAVED": "failed_saved", "FAILED_PUBLISHED": "failed_published",
    }
    assert {item.name: item.value for item in ClaimDisposition} == {
        "ACQUIRED": "acquired", "BUSY": "busy", "EXISTING": "existing",
    }
    assert ArtifactDescriptor("uri", HASH, 0).size_bytes == 0
    with pytest.raises((TypeError, ValueError)):
        ArtifactDescriptor("uri", HASH, True)
    context = DeliveryContext("tenant")
    with pytest.raises(FrozenInstanceError):
        context.authorized_tenant_id = "other"


def test_event_id_generator_port_uses_designed_method_name():
    assert "new_event_id" in EventIdGenerator.__dict__
    assert "generate" not in EventIdGenerator.__dict__


@pytest.mark.parametrize("lease", [None, datetime(2026, 1, 1), datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=1)))])
def test_claim_requires_aware_utc_lease(lease):
    with pytest.raises((TypeError, ValueError)):
        claimed(lease_expires_at=lease)


def test_zero_offset_timezone_is_accepted_as_utc():
    lease = datetime(2026, 1, 1, tzinfo=timezone(timedelta(0), "ZERO"))
    assert claimed(lease_expires_at=lease).lease_expires_at is lease


def test_all_models_are_frozen_and_direct_constructor_fields_are_validated():
    models = [
        ArtifactDescriptor("uri", HASH, 1),
        DeliveryContext("tenant"),
        claimed(),
        ClaimResult(ClaimDisposition.ACQUIRED, claimed()),
    ]
    for model in models:
        with pytest.raises(FrozenInstanceError):
            setattr(model, next(iter(model.__dataclass_fields__)), "changed")
    invalid_constructors = [
        lambda: ArtifactDescriptor("", HASH, 1),
        lambda: ArtifactDescriptor("uri", "A" * 64, 1),
        lambda: ArtifactDescriptor("uri", HASH, -1),
        lambda: DeliveryContext("tenant\nother"),
        lambda: claimed(key=""),
        lambda: claimed(payload_digest="short"),
        lambda: claimed(state="claimed"),
        lambda: claimed(claim_token=""),
        lambda: ClaimResult("acquired", claimed()),
        lambda: ClaimResult(ClaimDisposition.ACQUIRED, object()),
    ]
    for constructor in invalid_constructors:
        with pytest.raises((TypeError, ValueError)):
            constructor()


@pytest.mark.parametrize("state", [ProcessingState.SAVED, ProcessingState.PUBLISHED])
def test_each_success_state_requires_own_ready_event(state):
    ProcessingRecord("key", HASH, state, event(), "token", None)


@pytest.mark.parametrize("state", [ProcessingState.FAILED_SAVED, ProcessingState.FAILED_PUBLISHED])
def test_each_failure_state_requires_own_non_retryable_failure_event(state):
    ProcessingRecord("key", HASH, state, event("parser.failed.v1", False), "token", None)


def test_state_event_and_claim_disposition_invariants():
    ready = ProcessingRecord("key", HASH, ProcessingState.SAVED, event(), "token", None)
    failed = ProcessingRecord("key", HASH, ProcessingState.FAILED_SAVED, event("parser.failed.v1"), "token", None)
    ClaimResult(ClaimDisposition.ACQUIRED, claimed())
    ClaimResult(ClaimDisposition.BUSY, claimed())
    ClaimResult(ClaimDisposition.EXISTING, ready)
    for disposition, record in ((ClaimDisposition.EXISTING, claimed()), (ClaimDisposition.ACQUIRED, failed)):
        with pytest.raises(ValueError):
            ClaimResult(disposition, record)
    with pytest.raises(ValueError):
        ProcessingRecord("key", HASH, ProcessingState.SAVED, event("parser.failed.v1"), "token", None)
    with pytest.raises(ValueError):
        ProcessingRecord("key", HASH, ProcessingState.FAILED_SAVED, event("parser.failed.v1", True), "token", None)
