"""Metrics consumer contract, independently owned from Parser Service."""

from __future__ import annotations

from dataclasses import dataclass

from .envelope import require_hash, require_int, require_keys, require_literal_int, require_mapping, require_string


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
        return cls(require_string(mapping["uri"], "graph.uri"), require_hash(mapping["sha256"], "graph.sha256"), size, require_literal_int(mapping["schema_version"], 1, "graph.schema_version"), require_literal_int(mapping["parser_semantics_version"], 7, "graph.parser_semantics_version"), require_hash(mapping["graph_fingerprint"], "graph.graph_fingerprint"))

    def to_mapping(self) -> dict[str, object]:
        return {"uri": self.uri, "sha256": self.sha256, "size_bytes": self.size_bytes, "schema_version": self.schema_version, "parser_semantics_version": self.parser_semantics_version, "graph_fingerprint": self.graph_fingerprint}


@dataclass(frozen=True)
class GraphReady:
    source_uri: str
    graph: GraphDescriptor

    def __post_init__(self) -> None:
        require_string(self.source_uri, "source_uri")
        if type(self.graph) is not GraphDescriptor:
            raise TypeError("graph must be a GraphDescriptor")

    @classmethod
    def from_mapping(cls, value: object) -> GraphReady:
        mapping = require_mapping(value, "payload")
        require_keys(mapping, {"source_uri", "graph"}, "payload")
        return cls(require_string(mapping["source_uri"], "source_uri"), GraphDescriptor.from_mapping(mapping["graph"]))

    def to_mapping(self) -> dict[str, object]:
        return {"source_uri": self.source_uri, "graph": self.graph.to_mapping()}
