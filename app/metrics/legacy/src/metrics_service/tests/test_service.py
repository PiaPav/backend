import asyncio
import copy

import pytest

from metrics_service.application import MetricsHandler
from metrics_service.contracts import PermanentError, digest, encode, graph_event


def event():
    return {"event_id": "graph-1", "event_type": "graph.ready.v1", "schema_version": 1,
            "tenant_id": "tenant", "correlation_id": "analysis-1", "causation_id": "source-1",
            "occurred_at": "2026-10-29T10:00:00Z", "producer": {"service": "parser", "version": "1"},
            "payload": {"graph": {"uri": "s3://artifacts/tenants/tenant/graph.json",
                                  "sha256": digest(b"graph"), "size_bytes": 5,
                                  "schema_version": 1, "parser_semantics_version": 7,
                                  "graph_fingerprint": "a" * 64}}}


class Store:
    def __init__(self):
        self.data = {"tenants/tenant/graph.json": b"graph"}
    async def read(self, key, limit):
        return self.data.get(key)
    async def put_once(self, key, data):
        return self.data.setdefault(key, data)


class Engine:
    calls = 0
    async def calculate(self, raw, descriptor):
        self.calls += 1
        return encode({"schema_version": 1, "metrics_semantics_version": 4,
                       "input": {"graph_fingerprint": descriptor["graph_fingerprint"]}, "metrics": {}})


class Publisher:
    def __init__(self):
        self.events = []
        self.fail = False
    async def publish(self, output):
        if self.fail:
            raise ConnectionError("unavailable")
        self.events.append(output)


def test_linear_result_saved_before_publication_and_replayed_after_restart():
    async def scenario():
        store, engine, publisher = Store(), Engine(), Publisher()
        publisher.fail = True
        first = MetricsHandler(store, publisher, engine, "artifacts")
        with pytest.raises(ConnectionError):
            await first.handle(encode(event()))
        assert "tenants/tenant/metrics/v4/graph-1/event.json" in store.data
        publisher.fail = False
        restarted = MetricsHandler(store, publisher, engine, "artifacts")
        await restarted.handle(encode(event()))
        await restarted.handle(encode(event()))
        assert engine.calls == 1
        assert publisher.events[0] == publisher.events[1]
        assert publisher.events[0]["causation_id"] == "graph-1"
        assert publisher.events[0]["event_type"] == "metrics.ready.v1"
    asyncio.run(scenario())


def test_reused_event_id_cannot_change_input():
    async def scenario():
        store, engine, publisher = Store(), Engine(), Publisher()
        handler = MetricsHandler(store, publisher, engine, "artifacts")
        await handler.handle(encode(event()))
        changed = copy.deepcopy(event())
        changed["correlation_id"] = "other-analysis"
        with pytest.raises(PermanentError, match="reused"):
            await handler.handle(encode(changed))
        assert len(publisher.events) == 1
    asyncio.run(scenario())


def test_corrupt_source_never_reaches_core():
    async def scenario():
        store, engine, publisher = Store(), Engine(), Publisher()
        store.data["tenants/tenant/graph.json"] = b"wrong"
        with pytest.raises(PermanentError, match="checksum"):
            await MetricsHandler(store, publisher, engine, "artifacts").handle(encode(event()))
        assert engine.calls == 0
        assert not publisher.events
    asyncio.run(scenario())


@pytest.mark.parametrize("uri", ["s3://artifacts/tenants/other/graph.json", "file:///etc/passwd",
                                  "s3://artifacts/tenants/tenant/../graph", 3])
def test_storage_namespace_enforced(uri):
    value = event()
    value["payload"]["graph"]["uri"] = uri
    with pytest.raises(PermanentError):
        graph_event(encode(value), "artifacts", 100)


def test_concurrent_duplicates_share_result_event():
    async def scenario():
        store, engine, publisher = Store(), Engine(), Publisher()
        handler = MetricsHandler(store, publisher, engine, "artifacts")
        await asyncio.gather(handler.handle(encode(event())), handler.handle(encode(event())))
        assert len(publisher.events) == 2
        assert publisher.events[0] == publisher.events[1]
    asyncio.run(scenario())
