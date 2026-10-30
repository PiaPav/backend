"""Linear orchestration through storage, computation and broker ports."""
from __future__ import annotations

from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from .contracts import PermanentError, decode, digest, encode, graph_event


class ArtifactStore(Protocol):
    async def read(self, key: str, limit: int) -> bytes | None: ...
    async def put_once(self, key: str, data: bytes) -> bytes: ...


class Publisher(Protocol):
    async def publish(self, event: dict) -> None: ...


class MetricsEngine(Protocol):
    async def calculate(self, raw: bytes, descriptor: dict) -> bytes: ...


class MetricsHandler:
    def __init__(self, store: ArtifactStore, publisher: Publisher, engine: MetricsEngine,
                 bucket: str, max_graph_bytes: int = 67108864, max_metrics_bytes: int = 134217728):
        self.store, self.publisher, self.engine = store, publisher, engine
        self.bucket = bucket
        self.max_graph_bytes, self.max_metrics_bytes = max_graph_bytes, max_metrics_bytes

    async def handle(self, raw: bytes) -> None:
        event = graph_event(raw, self.bucket, self.max_graph_bytes)
        identity = f"tenants/{event['tenant_id']}/metrics/v4/{event['event_id']}"
        canonical = encode(event)
        claimed = await self.store.put_once(identity + "/input.json", canonical)
        if claimed != canonical:
            raise PermanentError("event id reused with different content")
        saved = await self.store.read(identity + "/event.json", 65536)
        if saved is not None:
            await self.publisher.publish(decode(saved))
            return
        graph = event["payload"]["graph"]
        metrics_key = identity + "/metrics.json"
        result = await self.store.read(metrics_key, self.max_metrics_bytes)
        if result is None:
            graph_key = graph["uri"].split("/", 3)[3]
            source = await self.store.read(graph_key, self.max_graph_bytes)
            if source is None:
                raise PermanentError("graph artifact not found")
            if len(source) != graph["size_bytes"] or digest(source) != graph["sha256"]:
                raise PermanentError("graph artifact checksum or size mismatch")
            result = await self.engine.calculate(source, graph)
            if len(result) > self.max_metrics_bytes:
                raise PermanentError("metrics artifact too large")
            persisted = await self.store.put_once(metrics_key, result)
            if persisted != result:
                raise PermanentError("conflicting metrics artifact")
        dto = decode(result)
        if (type(dto.get("schema_version")) is not int or dto["schema_version"] != 1
                or type(dto.get("metrics_semantics_version")) is not int or dto["metrics_semantics_version"] != 4
                or not isinstance(dto.get("input"), dict)
                or dto["input"].get("graph_fingerprint") != graph["graph_fingerprint"]):
            raise PermanentError("metrics output contract mismatch")
        output = {
            "event_id": str(uuid5(NAMESPACE_URL, identity + "/metrics.ready.v1")),
            "event_type": "metrics.ready.v1", "schema_version": 1,
            # Stable logical timestamp makes concurrent deliveries identical.
            "occurred_at": event["occurred_at"], "correlation_id": event["correlation_id"],
            "causation_id": event["event_id"], "tenant_id": event["tenant_id"],
            "producer": {"service": "metrics-service", "version": "1"},
            "payload": {"graph": {"uri": graph["uri"], "graph_fingerprint": graph["graph_fingerprint"]},
                        "metrics": {"uri": f"s3://{self.bucket}/{metrics_key}", "sha256": digest(result),
                                    "size_bytes": len(result), "schema_version": dto["schema_version"],
                                    "metrics_semantics_version": dto["metrics_semantics_version"]}},
        }
        saved = await self.store.put_once(identity + "/event.json", encode(output))
        if saved != encode(output):
            raise PermanentError("conflicting output event")
        await self.publisher.publish(decode(saved))
