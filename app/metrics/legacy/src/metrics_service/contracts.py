"""Versioned JSON contract; no transport dependencies."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from urllib.parse import urlsplit


class PermanentError(ValueError):
    """Invalid input that cannot be repaired by redelivery."""


def encode(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def decode(raw: bytes) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise PermanentError("duplicate JSON key")
            result[key] = value
        return result
    try:
        value = json.loads(raw, object_pairs_hook=pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(PermanentError("nonfinite JSON")))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise PermanentError("invalid JSON") from exc
    if not isinstance(value, dict):
        raise PermanentError("expected JSON object")
    return value


def graph_event(raw: bytes, bucket: str, max_bytes: int) -> dict:
    if len(raw) > 65536:
        raise PermanentError("event too large")
    event = decode(raw)
    if event.get("event_type") != "graph.ready.v1" or type(event.get("schema_version")) is not int or event["schema_version"] != 1:
        raise PermanentError("unsupported event")
    for key in ("event_id", "tenant_id", "correlation_id", "causation_id"):
        if not isinstance(event.get(key), str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", event[key]):
            raise PermanentError("invalid event identifier")
    try:
        stamp = event["occurred_at"]
        if not isinstance(stamp, str) or not stamp.endswith("Z"):
            raise ValueError()
        datetime.fromisoformat(stamp[:-1] + "+00:00")
        producer = event["producer"]
        if not isinstance(producer, dict) or any(not isinstance(producer.get(k), str) or not producer[k] for k in ("service", "version")):
            raise ValueError()
        graph = event["payload"]["graph"]
        if not isinstance(graph, dict):
            raise ValueError()
        for key in ("sha256", "graph_fingerprint"):
            if not isinstance(graph.get(key), str) or not re.fullmatch("[0-9a-f]{64}", graph[key]):
                raise ValueError()
        if type(graph.get("size_bytes")) is not int or not 0 < graph["size_bytes"] <= max_bytes:
            raise ValueError()
        if type(graph.get("schema_version")) is not int or graph["schema_version"] != 1:
            raise ValueError()
        if type(graph.get("parser_semantics_version")) is not int or graph["parser_semantics_version"] not in (6, 7):
            raise ValueError()
        if not isinstance(graph.get("uri"), str):
            raise ValueError()
        uri = urlsplit(graph["uri"])
        prefix = f"tenants/{event['tenant_id']}/"
        key = uri.path.removeprefix("/")
        if uri.scheme != "s3" or uri.netloc != bucket or uri.query or uri.fragment or not key.startswith(prefix):
            raise ValueError()
        if any(part in ("", ".", "..") for part in key.split("/")) or "%" in key or "\\" in key:
            raise ValueError()
    except (KeyError, TypeError, ValueError) as exc:
        raise PermanentError("invalid graph descriptor or envelope") from exc
    return event
