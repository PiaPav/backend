"""Parser output event payloads."""

from __future__ import annotations

from dataclasses import dataclass

from .envelope import (
    require_bool, require_hash, require_int, require_keys, require_literal_int,
    require_mapping, require_string,
)


@dataclass(frozen=True)
class GraphDescriptor:
    uri: str
    sha256: str
    size_bytes: int
    schema_version: int
    parser_semantics_version: int
    graph_fingerprint: str

    def __post_init__(self) -> None:
        require_string(self.uri, "graph.uri")
        require_hash(self.sha256, "graph.sha256")
        size = require_int(self.size_bytes, "graph.size_bytes")
        if size < 0:
            raise ValueError("graph.size_bytes must be nonnegative")
        require_literal_int(self.schema_version, 1, "graph.schema_version")
        require_literal_int(self.parser_semantics_version, 7, "graph.parser_semantics_version")
        require_hash(self.graph_fingerprint, "graph.graph_fingerprint")

    @classmethod
    def from_mapping(cls, value: object) -> GraphDescriptor:
        mapping = require_mapping(value, "graph")
        require_keys(mapping, {"uri", "sha256", "size_bytes", "schema_version", "parser_semantics_version", "graph_fingerprint"}, "graph")
        size = require_int(mapping["size_bytes"], "graph.size_bytes")
        if size < 0:
            raise ValueError("graph.size_bytes must be nonnegative")
        return cls(
            require_string(mapping["uri"], "graph.uri"),
            require_hash(mapping["sha256"], "graph.sha256"), size,
            require_literal_int(mapping["schema_version"], 1, "graph.schema_version"),
            require_literal_int(mapping["parser_semantics_version"], 7, "graph.parser_semantics_version"),
            require_hash(mapping["graph_fingerprint"], "graph.graph_fingerprint"),
        )

    def to_mapping(self) -> dict[str, object]:
        return {"uri": self.uri, "sha256": self.sha256, "size_bytes": self.size_bytes, "schema_version": self.schema_version, "parser_semantics_version": self.parser_semantics_version, "graph_fingerprint": self.graph_fingerprint}


@dataclass(frozen=True)
class SourceIndexDescriptor:
    uri: str
    sha256: str
    size_bytes: int
    schema_version: int
    project_fingerprint: str

    def __post_init__(self) -> None:
        require_string(self.uri, "source_index.uri")
        require_hash(self.sha256, "source_index.sha256")
        size = require_int(self.size_bytes, "source_index.size_bytes")
        if size < 0:
            raise ValueError("source_index.size_bytes must be nonnegative")
        require_literal_int(self.schema_version, 1, "source_index.schema_version")
        require_hash(self.project_fingerprint, "source_index.project_fingerprint")

    @classmethod
    def from_mapping(cls, value: object) -> SourceIndexDescriptor:
        mapping = require_mapping(value, "source_index")
        require_keys(mapping, {"uri", "sha256", "size_bytes", "schema_version", "project_fingerprint"}, "source_index")
        return cls(
            require_string(mapping["uri"], "source_index.uri"),
            require_hash(mapping["sha256"], "source_index.sha256"),
            require_int(mapping["size_bytes"], "source_index.size_bytes"),
            require_literal_int(mapping["schema_version"], 1, "source_index.schema_version"),
            require_hash(mapping["project_fingerprint"], "source_index.project_fingerprint"),
        )

    def to_mapping(self) -> dict[str, object]:
        return {"uri": self.uri, "sha256": self.sha256, "size_bytes": self.size_bytes,
                "schema_version": self.schema_version, "project_fingerprint": self.project_fingerprint}


@dataclass(frozen=True)
class GraphReady:
    source_uri: str
    graph: GraphDescriptor
    source_index: SourceIndexDescriptor | None = None

    def __post_init__(self) -> None:
        require_string(self.source_uri, "source_uri")
        if type(self.graph) is not GraphDescriptor:
            raise TypeError("graph must be a GraphDescriptor")
        if self.source_index is not None and type(self.source_index) is not SourceIndexDescriptor:
            raise TypeError("source_index must be a SourceIndexDescriptor")

    @classmethod
    def from_mapping(cls, value: object) -> GraphReady:
        mapping = require_mapping(value, "payload")
        expected = {"source_uri", "graph"} | ({"source_index"} if "source_index" in mapping else set())
        require_keys(mapping, expected, "payload")
        source_index = (SourceIndexDescriptor.from_mapping(mapping["source_index"])
                        if "source_index" in mapping else None)
        return cls(require_string(mapping["source_uri"], "source_uri"),
                   GraphDescriptor.from_mapping(mapping["graph"]), source_index)

    def to_mapping(self) -> dict[str, object]:
        result = {"source_uri": self.source_uri, "graph": self.graph.to_mapping()}
        if self.source_index is not None:
            result["source_index"] = self.source_index.to_mapping()
        return result


@dataclass(frozen=True)
class Failure:
    stage: str
    failed_event_id: str
    error_code: str
    message: str
    retryable: bool

    def __post_init__(self) -> None:
        if require_string(self.stage, "stage") != "parser":
            raise ValueError("parser failure stage must be parser")
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
        return cls(
            require_string(mapping["stage"], "stage"),
            require_string(mapping["failed_event_id"], "failed_event_id"),
            require_string(mapping["error_code"], "error_code"), message,
            require_bool(mapping["retryable"], "retryable"),
        )

    def to_mapping(self) -> dict[str, object]:
        return {"stage": self.stage, "failed_event_id": self.failed_event_id, "error_code": self.error_code, "message": self.message, "retryable": self.retryable}
