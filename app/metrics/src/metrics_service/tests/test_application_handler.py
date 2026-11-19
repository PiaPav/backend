from datetime import datetime, timezone

from metrics_service.application import DeliveryContext, DeliveryDecision, HandlerConfig, MetricsHandler
from metrics_service.application.errors import IdempotencyPayloadConflictError
from metrics_service.contracts import Producer


class _Unused:
    def __getattr__(self, name):
        raise AssertionError(f"dependency used before input validation: {name}")


class _Clock:
    def now(self):
        return datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_malformed_input_is_rejected_before_claim() -> None:
    unused = _Unused()
    handler = MetricsHandler(config=HandlerConfig(Producer("metrics-service", "1")), clock=_Clock(), ids=unused,
                             publisher=unused, idempotency=unused, graphs=unused, staging=unused,
                             artifacts=unused, metrics=unused, validator=unused)

    assert handler({"event_type": "graph.ready.v1"}, DeliveryContext("tenant")) is DeliveryDecision.REJECT


def _wire():
    digest = "a" * 64
    return {"event_id": "event-1", "event_type": "graph.ready.v1", "schema_version": 1,
            "occurred_at": "2026-10-24T12:00:00.123Z", "correlation_id": "analysis-1",
            "causation_id": "cause-1", "tenant_id": "tenant-1",
            "producer": {"service": "parser-service", "version": "1"},
            "payload": {"source_uri": "file:///source", "graph": {"uri": "file:///graph.json",
                "sha256": digest, "size_bytes": 0, "schema_version": 1,
                "parser_semantics_version": 7, "graph_fingerprint": digest}}}


class _Ids:
    def new_event_id(self):
        return "claim-token"


class _FailingClaim:
    def __init__(self, error):
        self.error = error
        self.calls = 0

    def claim(self, *args):
        self.calls += 1
        raise self.error


def _claim_handler(store):
    unused = _Unused()
    return MetricsHandler(config=HandlerConfig(Producer("metrics-service", "1")), clock=_Clock(), ids=_Ids(),
                          publisher=unused, idempotency=store, graphs=unused, staging=unused,
                          artifacts=unused, metrics=unused, validator=unused)


def test_unexpected_claim_exception_is_retried_without_processing() -> None:
    store = _FailingClaim(RuntimeError("database detail"))
    assert _claim_handler(store)(_wire(), DeliveryContext("tenant-1")) is DeliveryDecision.RETRY
    assert store.calls == 1


def test_claim_payload_conflict_is_rejected_without_processing() -> None:
    store = _FailingClaim(IdempotencyPayloadConflictError("Conflicting payload"))
    assert _claim_handler(store)(_wire(), DeliveryContext("tenant-1")) is DeliveryDecision.REJECT
    assert store.calls == 1
