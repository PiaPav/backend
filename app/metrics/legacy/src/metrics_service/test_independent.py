"""Independent pipeline and failure-boundary regression checks."""
import asyncio
from copy import deepcopy

import pytest

from graph_dto import graph_fingerprint
from parser import parse_project
from metrics_service.application import MetricsHandler
from metrics_service.contracts import PermanentError, decode, digest, encode, graph_event
from metrics_service.core_adapter import CoreMetricsEngine


class Store:
    def __init__(self, objects):
        self.objects = objects
        self.operations = []

    async def read(self, key, limit):
        self.operations.append(("read", key))
        value = self.objects.get(key)
        if value is not None and len(value) > limit:
            raise PermanentError("too large")
        return value

    async def put_once(self, key, data):
        self.operations.append(("put", key))
        return self.objects.setdefault(key, data)


class Publisher:
    def __init__(self, store):
        self.store = store
        self.events = []
        self.fail = False

    async def publish(self, event):
        identity = "tenants/team/metrics/v4/event-1"
        assert decode(self.store.objects[identity + "/event.json"]) == event
        assert identity + "/metrics.json" in self.store.objects
        if self.fail:
            raise ConnectionError("broker unavailable")
        self.events.append(event)


def event_for(raw, fingerprint):
    return {
        "event_id": "event-1", "event_type": "graph.ready.v1", "schema_version": 1,
        "tenant_id": "team", "correlation_id": "analysis-1", "causation_id": "parse-1",
        "occurred_at": "2026-10-29T12:00:00Z",
        "producer": {"service": "parser", "version": "1"},
        "payload": {"graph": {
            "uri": "s3://artifacts/tenants/team/graph.json", "sha256": digest(raw),
            "size_bytes": len(raw), "schema_version": 1, "parser_semantics_version": 7,
            "graph_fingerprint": fingerprint,
        }},
    }


def test_real_parser_metrics_pipeline_and_publish_failure_recovery(tmp_path):
    source = tmp_path / "project"
    source.mkdir()
    (source / "sample.py").write_text("def absolute(value):\n    if value < 0:\n        return -value\n    return value\n")
    graph_path = parse_project(source, tmp_path / "graph.json")
    raw = graph_path.read_bytes()
    event = event_for(raw, graph_fingerprint(decode(raw)))
    store = Store({"tenants/team/graph.json": raw})
    publisher = Publisher(store)
    handler = MetricsHandler(store, publisher, CoreMetricsEngine(), "artifacts")

    async def scenario():
        publisher.fail = True
        with pytest.raises(ConnectionError):
            await handler.handle(encode(event))
        # Recovery must depend only on durable artifacts, even after source deletion.
        del store.objects["tenants/team/graph.json"]
        publisher.fail = False
        await handler.handle(encode(event))
        await handler.handle(encode(event))

    asyncio.run(scenario())
    assert len(publisher.events) == 2
    assert publisher.events[0] == publisher.events[1]
    output = publisher.events[0]
    assert output["correlation_id"] == "analysis-1"
    assert output["causation_id"] == "event-1"
    descriptor = output["payload"]["metrics"]
    result = store.objects[descriptor["uri"].split("/", 3)[3]]
    assert descriptor["sha256"] == digest(result)
    assert descriptor["size_bytes"] == len(result)
    assert decode(result)["input"]["graph_fingerprint"] == event["payload"]["graph"]["graph_fingerprint"]


@pytest.mark.parametrize("uri", [1, [], {}, None, "s3://artifacts/tenants/other/graph.json", "s3://artifacts/tenants/team/../graph.json"])
def test_invalid_artifact_reference_is_permanent(uri):
    event = event_for(b"{}", "a" * 64)
    event["payload"]["graph"]["uri"] = uri
    with pytest.raises(PermanentError):
        graph_event(encode(event), "artifacts", 1024)


def test_checksum_failure_and_conflicting_event_id_never_publish():
    event = event_for(b"{}", "a" * 64)
    store = Store({"tenants/team/graph.json": b"[]"})
    publisher = Publisher(store)
    handler = MetricsHandler(store, publisher, CoreMetricsEngine(), "artifacts")

    async def scenario():
        with pytest.raises(PermanentError, match="checksum"):
            await handler.handle(encode(event))
        conflict = deepcopy(event)
        conflict["correlation_id"] = "another-analysis"
        with pytest.raises(PermanentError, match="reused"):
            await handler.handle(encode(conflict))

    asyncio.run(scenario())
    assert not publisher.events
    assert not any(key.endswith("/metrics.json") for key in store.objects)
