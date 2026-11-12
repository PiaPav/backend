"""Canonical JSON codec for Metrics Service wire events."""

from __future__ import annotations

import json

from .commands import GraphReady
from .envelope import EventEnvelope, parse_envelope_fields, require_mapping
from .events import Failure, MetricsReady

GRAPH_READY = "graph.ready.v1"
METRICS_READY = "metrics.ready.v1"
METRICS_FAILED = "metrics.failed.v1"
_PAYLOADS = {GRAPH_READY: GraphReady, METRICS_READY: MetricsReady, METRICS_FAILED: Failure}


def from_mapping(value: object) -> EventEnvelope:
    mapping, fields = parse_envelope_fields(value)
    event_type = fields["event_type"]
    payload_type = _PAYLOADS.get(event_type)
    if payload_type is None:
        raise ValueError(f"unsupported event_type: {event_type}")
    payload = payload_type.from_mapping(mapping["payload"])
    if event_type == METRICS_FAILED and payload.stage != "metrics":
        raise ValueError("metrics.failed.v1 stage must be metrics")
    return EventEnvelope(payload=payload, **fields)


def to_mapping(event: EventEnvelope) -> dict[str, object]:
    payload_type = _PAYLOADS.get(event.event_type)
    if payload_type is None or type(event.payload) is not payload_type:
        raise ValueError("event_type and payload type must be an exact known pair")
    return from_mapping(event.to_mapping()).to_mapping()


def encode_json(event: EventEnvelope) -> bytes:
    return json.dumps(to_mapping(event), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def decode_json(value: bytes | str) -> EventEnvelope:
    if not isinstance(value, (bytes, str)):
        raise TypeError("JSON input must be bytes or string")
    try:
        text = value.decode("utf-8") if isinstance(value, bytes) else value
        decoded = json.loads(
            text, object_pairs_hook=_unique_object, parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("invalid UTF-8 JSON event") from error
    return from_mapping(require_mapping(decoded, "envelope"))


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise ValueError(f"non-standard JSON constant: {value}")
