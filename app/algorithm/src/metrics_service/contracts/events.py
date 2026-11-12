"""Metrics output event payloads."""

from __future__ import annotations

from dataclasses import dataclass

from .envelope import require_bool, require_hash, require_int, require_keys, require_literal_int, require_mapping, require_string


@dataclass(frozen=True)
class GraphReference:
    uri: str
    graph_fingerprint: str

    def __post_init__(self) -> None:
        require_string(self.uri, "graph.uri")
        require_hash(self.graph_fingerprint, "graph.graph_fingerprint")

    @classmethod
    def from_mapping(cls, value: object) -> GraphReference:
        mapping = require_mapping(value, "graph")
        require_keys(mapping, {"uri", "graph_fingerprint"}, "graph")
        return cls(require_string(mapping["uri"], "graph.uri"), require_hash(mapping["graph_fingerprint"], "graph.graph_fingerprint"))

    def to_mapping(self) -> dict[str, object]:
        return {"uri": self.uri, "graph_fingerprint": self.graph_fingerprint}


@dataclass(frozen=True)
class MetricsDescriptor:
    uri: str
    sha256: str
    size_bytes: int
    schema_version: int
    metrics_semantics_version: int

    def __post_init__(self) -> None:
        require_string(self.uri, "metrics.uri")
        require_hash(self.sha256, "metrics.sha256")
        size = require_int(self.size_bytes, "metrics.size_bytes")
        if size < 0:
            raise ValueError("metrics.size_bytes must be nonnegative")
        require_literal_int(self.schema_version, 1, "metrics.schema_version")
        require_literal_int(self.metrics_semantics_version, 4, "metrics.metrics_semantics_version")

    @classmethod
    def from_mapping(cls, value: object) -> MetricsDescriptor:
        mapping = require_mapping(value, "metrics")
        require_keys(mapping, {"uri", "sha256", "size_bytes", "schema_version", "metrics_semantics_version"}, "metrics")
        size = require_int(mapping["size_bytes"], "metrics.size_bytes")
        if size < 0:
            raise ValueError("metrics.size_bytes must be nonnegative")
        return cls(require_string(mapping["uri"], "metrics.uri"), require_hash(mapping["sha256"], "metrics.sha256"), size, require_literal_int(mapping["schema_version"], 1, "metrics.schema_version"), require_literal_int(mapping["metrics_semantics_version"], 4, "metrics.metrics_semantics_version"))

    def to_mapping(self) -> dict[str, object]:
        return {"uri": self.uri, "sha256": self.sha256, "size_bytes": self.size_bytes, "schema_version": self.schema_version, "metrics_semantics_version": self.metrics_semantics_version}


@dataclass(frozen=True)
class MetricsReady:
    graph: GraphReference
    metrics: MetricsDescriptor

    def __post_init__(self) -> None:
        if type(self.graph) is not GraphReference:
            raise TypeError("graph must be a GraphReference")
        if type(self.metrics) is not MetricsDescriptor:
            raise TypeError("metrics must be a MetricsDescriptor")

    @classmethod
    def from_mapping(cls, value: object) -> MetricsReady:
        mapping = require_mapping(value, "payload")
        require_keys(mapping, {"graph", "metrics"}, "payload")
        return cls(GraphReference.from_mapping(mapping["graph"]), MetricsDescriptor.from_mapping(mapping["metrics"]))

    def to_mapping(self) -> dict[str, object]:
        return {"graph": self.graph.to_mapping(), "metrics": self.metrics.to_mapping()}


@dataclass(frozen=True)
class Failure:
    stage: str
    failed_event_id: str
    error_code: str
    message: str
    retryable: bool

    def __post_init__(self) -> None:
        if require_string(self.stage, "stage") != "metrics":
            raise ValueError("metrics failure stage must be metrics")
        require_string(self.failed_event_id, "failed_event_id")
        require_string(self.error_code, "error_code")
        message = require_string(self.message, "message")
        if any(ord(character) < 32 for character in message):
            raise ValueError("message must not contain control characters")
        require_bool(self.retryable, "retryable")

    @classmethod
    def from_mapping(cls, value: object) -> Failure:
        mapping = require_mapping(value, "payload")
        require_keys(mapping, {"stage", "failed_event_id", "error_code", "message", "retryable"}, "payload")
        message = require_string(mapping["message"], "message")
        if any(ord(character) < 32 for character in message):
            raise ValueError("message must not contain control characters")
        return cls(require_string(mapping["stage"], "stage"), require_string(mapping["failed_event_id"], "failed_event_id"), require_string(mapping["error_code"], "error_code"), message, require_bool(mapping["retryable"], "retryable"))

    def to_mapping(self) -> dict[str, object]:
        return {"stage": self.stage, "failed_event_id": self.failed_event_id, "error_code": self.error_code, "message": self.message, "retryable": self.retryable}
