import hashlib
from contextlib import nullcontext
from datetime import datetime, timezone

import pytest

from parser_service.application import DeliveryContext, DeliveryDecision, HandlerConfig, ParserHandler
from parser_service.application.errors import InvalidGraphDtoError
from parser_service.application.models import (
    ArtifactDescriptor, ClaimDisposition, ClaimResult, ProcessingRecord, ProcessingState,
)
from parser_service.contracts import Producer


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def wire():
    return {"event_id": "event-1", "event_type": "parser.start.v1", "schema_version": 1,
            "occurred_at": "2026-10-24T12:00:00.123Z", "correlation_id": "analysis-1",
            "causation_id": "cause-1", "tenant_id": "tenant-1",
            "producer": {"service": "caller", "version": "1"},
            "payload": {"source_uri": "file:///source", "requested_graph": {
                "schema_version": 1, "parser_semantics_version": 7}}}


class Fakes:
    def __init__(self, tmp_path):
        self.source = tmp_path / "source"; self.source.write_bytes(b"source")
        self.target = tmp_path / "graph"; self.index_target = tmp_path / "source-index"
        self.output = b'{"nodes":[]}'
        self.index_output = b'{"schema_version":1}'
        self.calls = []; self.record = None; self.disposition = ClaimDisposition.ACQUIRED
        self.publish_error = None; self.validator_error = None; self.core_error = None; self.core_calls = 0
        self.record_saved_error = None; self.record_failure_error = None; self.record_published_error = None
        self.id_error_on_call = None; self.clock_error_on_call = None; self.id_calls = 0; self.clock_calls = 0

    def now(self):
        self.clock_calls += 1
        if self.clock_error_on_call == self.clock_calls: raise RuntimeError("clock failed")
        return NOW
    def new_event_id(self):
        self.id_calls += 1
        if self.id_error_on_call == self.id_calls: raise RuntimeError("id failed")
        return "generated-id"
    def materialize(self, uri): return nullcontext(self.source)
    def create_target(self, key):
        return nullcontext(self.index_target if key.startswith("source-index/") else self.target)
    def parse(self, source, target, source_index_target):
        self.core_calls += 1
        if self.core_error: raise self.core_error
        target.write_bytes(self.output); source_index_target.write_bytes(self.index_output)
        return target, source_index_target
    def validate(self, path):
        if self.validator_error: raise self.validator_error
        return "f" * 64
    def validate_source_index(self, path):
        if self.validator_error: raise self.validator_error
        return "e" * 64
    def save(self, path, key):
        content = path.read_bytes()
        uri = "file:///stored-source-index" if key.startswith("source-index/") else "file:///stored-graph"
        return ArtifactDescriptor(uri, hashlib.sha256(content).hexdigest(), len(content))
    def claim(self, key, digest, token, lease):
        self.key, self.digest = key, digest
        if self.record is None:
            self.record = ProcessingRecord(key, digest, ProcessingState.CLAIMED, None, token, lease)
        return ClaimResult(self.disposition, self.record)
    def record_saved(self, key, token, event):
        if self.record_saved_error: raise self.record_saved_error
        self.calls.append(("record_saved", event)); self.record = ProcessingRecord(key, self.digest, ProcessingState.SAVED, event, token, None); return self.record
    def record_failure(self, key, token, event):
        if self.record_failure_error: raise self.record_failure_error
        self.calls.append(("record_failure", event)); self.record = ProcessingRecord(key, self.digest, ProcessingState.FAILED_SAVED, event, token, None); return self.record
    def publish(self, event):
        self.calls.append(("publish", event))
        if self.publish_error: raise self.publish_error
    def record_published(self, key, token):
        if self.record_published_error: raise self.record_published_error
        self.calls.append(("record_published", self.record.output_event)); return self.record


def handler(f):
    return ParserHandler(config=HandlerConfig(Producer("parser-service", "1")), clock=f, ids=f,
                         publisher=f, idempotency=f, sources=f, staging=f, artifacts=f, parser=f, validator=f)


def test_happy_path_descriptor_fingerprint_and_order(tmp_path):
    f = Fakes(tmp_path)
    assert handler(f)(wire(), DeliveryContext("tenant-1")) is DeliveryDecision.ACK
    assert [x[0] for x in f.calls] == ["record_saved", "publish", "record_published"]
    event = f.calls[0][1]
    assert f.calls[1][1] is event and f.calls[2][1] is event
    assert event.payload.graph.uri == "file:///stored-graph"
    assert event.payload.graph.sha256 == hashlib.sha256(f.output).hexdigest()
    assert event.payload.graph.size_bytes == len(f.output)
    assert (event.payload.graph.schema_version, event.payload.graph.parser_semantics_version) == (1, 7)
    assert event.payload.graph.graph_fingerprint == "f" * 64
    assert event.payload.source_index.uri == "file:///stored-source-index"
    assert event.payload.source_index.sha256 == hashlib.sha256(f.index_output).hexdigest()
    assert event.payload.source_index.size_bytes == len(f.index_output)
    assert event.payload.source_index.schema_version == 1
    assert event.payload.source_index.project_fingerprint == "e" * 64
    assert (event.correlation_id, event.causation_id, event.tenant_id) == ("analysis-1", "event-1", "tenant-1")
    assert event.producer == Producer("parser-service", "1") and event.occurred_at == "2026-01-01T00:00:00Z"


@pytest.mark.parametrize("state", [ProcessingState.SAVED, ProcessingState.FAILED_SAVED])
def test_existing_saved_republishes_exact_event_then_marks_without_core(tmp_path, state):
    f = Fakes(tmp_path); handler(f)(wire(), DeliveryContext("tenant-1")); event = f.record.output_event
    if state is ProcessingState.FAILED_SAVED:
        f.validator_error = InvalidGraphDtoError("bad graph"); f.record = None; f.calls.clear(); handler(f)(wire(), DeliveryContext("tenant-1")); event = f.record.output_event
    f.record = ProcessingRecord(f.key, f.digest, state, event, "old-token", None)
    f.disposition = ClaimDisposition.EXISTING; f.calls.clear(); before = f.core_calls
    assert handler(f)(wire(), DeliveryContext("tenant-1")) is DeliveryDecision.ACK
    assert f.calls == [("publish", event), ("record_published", event)] and f.core_calls == before


@pytest.mark.parametrize("state", [ProcessingState.PUBLISHED, ProcessingState.FAILED_PUBLISHED])
def test_existing_published_acks_without_publication_or_core(tmp_path, state):
    f = Fakes(tmp_path); handler(f)(wire(), DeliveryContext("tenant-1")); event = f.record.output_event
    if state is ProcessingState.FAILED_PUBLISHED:
        f.validator_error = InvalidGraphDtoError("bad graph"); f.record = None; f.calls.clear(); handler(f)(wire(), DeliveryContext("tenant-1")); event = f.record.output_event
    f.record = ProcessingRecord(f.key, f.digest, state, event, "old-token", None); f.disposition = ClaimDisposition.EXISTING
    f.calls.clear(); before = f.core_calls
    assert handler(f)(wire(), DeliveryContext("tenant-1")) is DeliveryDecision.ACK
    assert f.calls == [] and f.core_calls == before


def test_busy_and_digest_mismatch_do_not_run_core(tmp_path):
    f = Fakes(tmp_path); h = handler(f); h(wire(), DeliveryContext("tenant-1"))
    f.disposition = ClaimDisposition.BUSY; f.record = ProcessingRecord(f.key, f.digest, ProcessingState.CLAIMED, None, "t", NOW)
    before = f.core_calls; assert h(wire(), DeliveryContext("tenant-1")) is DeliveryDecision.RETRY; assert f.core_calls == before
    f.record = ProcessingRecord(f.key, "0" * 64, ProcessingState.CLAIMED, None, "t", NOW)
    assert h(wire(), DeliveryContext("tenant-1")) is DeliveryDecision.REJECT; assert f.core_calls == before


def test_terminal_validator_failure_is_persisted_before_exact_publication_and_mark(tmp_path):
    f = Fakes(tmp_path); f.validator_error = InvalidGraphDtoError("bad graph")
    assert handler(f)(wire(), DeliveryContext("tenant-1")) is DeliveryDecision.ACK
    assert [x[0] for x in f.calls] == ["record_failure", "publish", "record_published"]
    failure = f.calls[0][1]
    assert f.calls[1][1] is failure and f.calls[2][1] is failure
    assert failure.payload.retryable is False and failure.payload.error_code == "invalid_graph_dto"
    assert (failure.correlation_id, failure.causation_id, failure.tenant_id) == ("analysis-1", "event-1", "tenant-1")
    assert failure.producer == Producer("parser-service", "1") and failure.occurred_at == "2026-01-01T00:00:00Z"


def test_terminal_core_failure_is_persisted(tmp_path):
    f = Fakes(tmp_path); f.core_error = InvalidGraphDtoError("bad core output")
    assert handler(f)(wire(), DeliveryContext("tenant-1")) is DeliveryDecision.ACK
    assert [x[0] for x in f.calls] == ["record_failure", "publish", "record_published"]


def test_unexpected_replay_publisher_exception_retries_without_core(tmp_path):
    f = Fakes(tmp_path); handler(f)(wire(), DeliveryContext("tenant-1")); before = f.core_calls
    f.disposition = ClaimDisposition.EXISTING; f.publish_error = RuntimeError("broker"); f.calls.clear()
    assert handler(f)(wire(), DeliveryContext("tenant-1")) is DeliveryDecision.RETRY
    assert [x[0] for x in f.calls] == ["publish"] and f.core_calls == before


@pytest.mark.parametrize("field,error", [("core_error", OSError("core")),
                                          ("validator_error", RuntimeError("validator"))])
def test_unexpected_processing_exception_retries_without_failure(tmp_path, field, error):
    f = Fakes(tmp_path); setattr(f, field, error)
    assert handler(f)(wire(), DeliveryContext("tenant-1")) is DeliveryDecision.RETRY
    assert not any(call[0] == "record_failure" for call in f.calls)


def test_record_saved_exception_retries_without_publish_or_failure(tmp_path):
    f = Fakes(tmp_path); f.record_saved_error = OSError("store")
    assert handler(f)(wire(), DeliveryContext("tenant-1")) is DeliveryDecision.RETRY
    assert f.calls == []


def test_record_failure_exception_retries(tmp_path):
    f = Fakes(tmp_path); f.validator_error = InvalidGraphDtoError("bad graph"); f.record_failure_error = OSError("store")
    assert handler(f)(wire(), DeliveryContext("tenant-1")) is DeliveryDecision.RETRY
    assert f.calls == []


def test_record_published_exception_retries_with_saved_replayable_state(tmp_path):
    f = Fakes(tmp_path); f.record_published_error = RuntimeError("mark")
    assert handler(f)(wire(), DeliveryContext("tenant-1")) is DeliveryDecision.RETRY
    assert [call[0] for call in f.calls] == ["record_saved", "publish"]
    assert f.record.state is ProcessingState.SAVED


@pytest.mark.parametrize("dependency", ["id", "clock"])
def test_identity_or_clock_exception_before_claim_retries(tmp_path, dependency):
    f = Fakes(tmp_path); setattr(f, dependency + "_error_on_call", 1)
    assert handler(f)(wire(), DeliveryContext("tenant-1")) is DeliveryDecision.RETRY
    assert not hasattr(f, "key")


@pytest.mark.parametrize("dependency", ["id", "clock"])
def test_identity_or_clock_exception_building_failure_retries(tmp_path, dependency):
    f = Fakes(tmp_path); f.validator_error = InvalidGraphDtoError("bad graph")
    setattr(f, dependency + "_error_on_call", 2)
    assert handler(f)(wire(), DeliveryContext("tenant-1")) is DeliveryDecision.RETRY
    assert f.calls == []


@pytest.mark.parametrize("terminal", [False, True])
def test_publish_failure_retries_and_next_delivery_replays_persisted_event(tmp_path, terminal):
    f = Fakes(tmp_path)
    if terminal: f.validator_error = InvalidGraphDtoError("bad graph")
    f.publish_error = RuntimeError("broker")
    assert handler(f)(wire(), DeliveryContext("tenant-1")) is DeliveryDecision.RETRY
    persisted = f.record.output_event
    assert [x[0] for x in f.calls] == (["record_failure", "publish"] if terminal else ["record_saved", "publish"])
    f.publish_error = None; f.disposition = ClaimDisposition.EXISTING; f.calls.clear(); before = f.core_calls
    assert handler(f)(wire(), DeliveryContext("tenant-1")) is DeliveryDecision.ACK
    assert f.calls == [("publish", persisted), ("record_published", persisted)] and f.core_calls == before


@pytest.mark.parametrize("bad_wire,tenant", [({"event_type": "parser.start.v1"}, "tenant-1"), (wire() | {"event_type": 4}, "tenant-1"), (wire(), "other")])
def test_invalid_inputs_reject_before_claim(tmp_path, bad_wire, tenant):
    f = Fakes(tmp_path)
    assert handler(f)(bad_wire, DeliveryContext(tenant)) is DeliveryDecision.REJECT
    assert not hasattr(f, "key")
