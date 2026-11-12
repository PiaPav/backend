"""Strict wire envelope primitives owned by Metrics Service."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Mapping

_RFC3339_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d+)?Z$")


def require_mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise TypeError(f"{name} keys must be strings")
    return value


def require_keys(value: Mapping[str, object], expected: set[str], name: str) -> None:
    actual = set(value)
    if actual != expected:
        raise ValueError(f"{name} fields differ: missing={sorted(expected - actual)}, extra={sorted(actual - expected)}")


def require_string(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if not value:
        raise ValueError(f"{name} must not be empty")
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise ValueError(f"{name} must not contain Unicode surrogate code points")
    return value


def require_int(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an integer")
    return value


def require_bool(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{name} must be a boolean")
    return value


def require_literal_int(value: object, expected: int, name: str) -> int:
    result = require_int(value, name)
    if result != expected:
        raise ValueError(f"{name} must be {expected}")
    return result


def require_hash(value: object, name: str) -> str:
    result = require_string(value, name)
    if re.fullmatch(r"[0-9a-f]{64}", result) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256 value")
    return result


def require_timestamp(value: object) -> str:
    result = require_string(value, "occurred_at")
    if _RFC3339_UTC.fullmatch(result) is None:
        raise ValueError("occurred_at must be UTC RFC3339 ending in Z")
    try:
        datetime.fromisoformat(result[:-1] + "+00:00")
    except ValueError as error:
        raise ValueError("occurred_at must be a valid UTC RFC3339 timestamp") from error
    return result


@dataclass(frozen=True)
class Producer:
    service: str
    version: str

    def __post_init__(self) -> None:
        require_string(self.service, "producer.service")
        require_string(self.version, "producer.version")

    @classmethod
    def from_mapping(cls, value: object) -> Producer:
        mapping = require_mapping(value, "producer")
        require_keys(mapping, {"service", "version"}, "producer")
        return cls(require_string(mapping["service"], "producer.service"), require_string(mapping["version"], "producer.version"))

    def to_mapping(self) -> dict[str, object]:
        return {"service": self.service, "version": self.version}


ENVELOPE_FIELDS = {"event_id", "event_type", "schema_version", "occurred_at", "correlation_id", "causation_id", "tenant_id", "producer", "payload"}


@dataclass(frozen=True)
class EventEnvelope:
    event_id: str
    event_type: str
    schema_version: int
    occurred_at: str
    correlation_id: str
    causation_id: str
    tenant_id: str
    producer: Producer
    payload: object

    def __post_init__(self) -> None:
        require_string(self.event_id, "event_id")
        require_string(self.event_type, "event_type")
        require_literal_int(self.schema_version, 1, "schema_version")
        require_timestamp(self.occurred_at)
        require_string(self.correlation_id, "correlation_id")
        require_string(self.causation_id, "causation_id")
        require_string(self.tenant_id, "tenant_id")
        if type(self.producer) is not Producer:
            raise TypeError("producer must be a Producer")

        from .commands import GraphReady
        from .events import Failure, MetricsReady
        payload_types = {
            "graph.ready.v1": GraphReady,
            "metrics.ready.v1": MetricsReady,
            "metrics.failed.v1": Failure,
        }
        payload_type = payload_types.get(self.event_type)
        if payload_type is None or type(self.payload) is not payload_type:
            raise ValueError("event_type and payload type must be an exact known pair")

    def to_mapping(self) -> dict[str, object]:
        payload = self.payload
        if not hasattr(payload, "to_mapping"):
            raise TypeError("payload must provide to_mapping()")
        return {"event_id": self.event_id, "event_type": self.event_type, "schema_version": self.schema_version, "occurred_at": self.occurred_at, "correlation_id": self.correlation_id, "causation_id": self.causation_id, "tenant_id": self.tenant_id, "producer": self.producer.to_mapping(), "payload": payload.to_mapping()}


def parse_envelope_fields(value: object) -> tuple[Mapping[str, object], dict[str, object]]:
    mapping = require_mapping(value, "envelope")
    require_keys(mapping, ENVELOPE_FIELDS, "envelope")
    return mapping, {
        "event_id": require_string(mapping["event_id"], "event_id"),
        "event_type": require_string(mapping["event_type"], "event_type"),
        "schema_version": require_literal_int(mapping["schema_version"], 1, "schema_version"),
        "occurred_at": require_timestamp(mapping["occurred_at"]),
        "correlation_id": require_string(mapping["correlation_id"], "correlation_id"),
        "causation_id": require_string(mapping["causation_id"], "causation_id"),
        "tenant_id": require_string(mapping["tenant_id"], "tenant_id"),
        "producer": Producer.from_mapping(mapping["producer"]),
    }
