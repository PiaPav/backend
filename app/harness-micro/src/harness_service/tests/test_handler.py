import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from harness_service.harness_handler import (
    ArtifactDescriptor,
    Claim,
    ClaimDisposition,
    DeliveryContext,
    DeliveryDecision,
    HarnessHandler,
    MaterializedInputs,
    Producer,
)
from harness_service.harness_runner import HarnessResult


HASH = "a" * 64


def wire() -> dict[str, object]:
    return {
        "event_id": "metrics-event-1",
        "event_type": "harness.start.v1",
        "schema_version": 1,
        "occurred_at": "2026-11-20T12:00:00Z",
        "correlation_id": "analysis-1",
        "causation_id": "metrics-event-1",
        "tenant_id": "tenant-1",
        "producer": {"service": "analysis-coordinator", "version": "1"},
        "payload": {
            "source_uri": "s3://artifacts/tenants/tenant-1/source.tar.zst",
            "graph": {
                "uri": "s3://artifacts/tenants/tenant-1/graph.json",
                "sha256": HASH,
                "size_bytes": 10,
                "schema_version": 1,
                "parser_semantics_version": 7,
                "graph_fingerprint": HASH,
            },
            "metrics": {
                "uri": "s3://artifacts/tenants/tenant-1/metrics.json",
                "sha256": HASH,
                "size_bytes": 20,
                "schema_version": 1,
                "metrics_semantics_version": 4,
                "graph_fingerprint": HASH,
            },
            "source_index": {
                "uri": "s3://artifacts/tenants/tenant-1/source-index.json",
                "sha256": HASH,
                "size_bytes": 30,
                "schema_version": 1,
                "project_fingerprint": "b" * 64,
            },
        },
    }


class FixedClock:
    def now(self):
        return datetime(2026, 11, 20, 15, 30, tzinfo=timezone.utc)


class Runner:
    def __init__(self, order):
        self.order = order
        self.calls = 0

    async def execute(self, request):
        self.calls += 1
        self.order.append("run")
        assert request.graph_path == Path("graph.json")
        return HarnessResult('{"status":"ok"}')


class Materializer:
    @contextmanager
    def materialize(self, **descriptors):
        assert set(descriptors) == {"source_uri", "graph", "metrics", "source_index"}
        assert descriptors["source_uri"].endswith("source.tar.zst")
        yield MaterializedInputs(Path("graph.json"), Path("metrics.json"), Path("source-index.json"))


class ResultStore:
    def __init__(self, order):
        self.order = order

    async def save(self, **values):
        self.order.append("save")
        assert values == {"tenant_id": "tenant-1", "event_id": "metrics-event-1",
                          "content": '{"status":"ok"}'}
        return ArtifactDescriptor("s3://artifacts/result.json", HASH, 15, 1)


class Idempotency:
    def __init__(self, order, claim=None):
        self.order = order
        self.result = claim or Claim(ClaimDisposition.NEW, "token")
        self.saved = None

    async def claim(self, **values):
        assert values["key"].startswith("harness:")
        assert len(values["payload_digest"]) == 64
        return self.result

    async def save_output(self, **values):
        self.order.append("persist")
        self.saved = values["output_event"]

    async def mark_published(self, **values):
        self.order.append("published")


class Publisher:
    def __init__(self, order, error=None):
        self.order = order
        self.error = error
        self.events = []

    async def publish(self, event):
        self.order.append("publish")
        if self.error:
            raise self.error
        self.events.append(event)


def handler(order, *, claim=None, publish_error=None):
    runner = Runner(order)
    state = Idempotency(order, claim)
    publisher = Publisher(order, publish_error)
    return HarnessHandler(
        runner=runner,
        materializer=Materializer(),
        result_store=ResultStore(order),
        idempotency=state,
        publisher=publisher,
        producer=Producer("harness-service", "test"),
        clock=FixedClock(),
    ), runner, state, publisher


def test_success_saves_before_confirmed_publish() -> None:
    order = []
    application, runner, state, publisher = handler(order)

    decision = asyncio.run(application.handle(wire(), DeliveryContext("tenant-1")))

    assert decision is DeliveryDecision.ACK
    assert order == ["run", "save", "persist", "publish", "published"]
    assert runner.calls == 1
    event = publisher.events[0]
    assert event["event_type"] == "harness.completed.v1"
    assert event["occurred_at"] == "2026-11-20T15:30:00Z"
    assert event["producer"] == {"service": "harness-service", "version": "test"}
    assert state.saved == event


def test_publish_failure_retries_after_persisting_result() -> None:
    order = []
    application, runner, state, _ = handler(order, publish_error=OSError("broker unavailable"))

    decision = asyncio.run(application.handle(wire(), DeliveryContext("tenant-1")))

    assert decision is DeliveryDecision.RETRY
    assert runner.calls == 1
    assert state.saved is not None
    assert order == ["run", "save", "persist", "publish"]


def test_saved_event_is_republished_without_llm_call() -> None:
    saved = {"event_type": "harness.completed.v1"}
    order = []
    application, runner, _, publisher = handler(
        order, claim=Claim(ClaimDisposition.SAVED, "saved-token", saved)
    )

    decision = asyncio.run(application.handle(wire(), DeliveryContext("tenant-1")))

    assert decision is DeliveryDecision.ACK
    assert runner.calls == 0
    assert publisher.events == [saved]
    assert order == ["publish", "published"]


def test_contract_and_trusted_tenant_are_checked_before_processing() -> None:
    order = []
    application, runner, _, _ = handler(order)
    invalid = wire()
    invalid["unexpected"] = True

    assert asyncio.run(application.handle(invalid, DeliveryContext("tenant-1"))) is DeliveryDecision.REJECT
    assert asyncio.run(application.handle(wire(), DeliveryContext("other"))) is DeliveryDecision.REJECT
    assert runner.calls == 0
    assert order == []


def test_graph_and_source_index_fingerprints_are_independent() -> None:
    order = []
    application, runner, _, _ = handler(order)

    assert asyncio.run(application.handle(wire(), DeliveryContext("tenant-1"))) is DeliveryDecision.ACK
    assert runner.calls == 1


def test_metrics_must_refer_to_input_graph() -> None:
    order = []
    application, runner, _, _ = handler(order)
    invalid = wire()
    invalid["payload"]["metrics"]["graph_fingerprint"] = "c" * 64

    assert asyncio.run(application.handle(invalid, DeliveryContext("tenant-1"))) is DeliveryDecision.REJECT
    assert runner.calls == 0
    assert order == []
