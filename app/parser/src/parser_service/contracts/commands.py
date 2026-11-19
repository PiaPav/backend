"""Parser input command contracts."""

from __future__ import annotations

from dataclasses import dataclass

from .envelope import require_keys, require_literal_int, require_mapping, require_string


@dataclass(frozen=True)
class RequestedGraph:
    schema_version: int
    parser_semantics_version: int

    def __post_init__(self) -> None:
        require_literal_int(self.schema_version, 1, "requested_graph.schema_version")
        require_literal_int(self.parser_semantics_version, 7, "requested_graph.parser_semantics_version")

    @classmethod
    def from_mapping(cls, value: object) -> RequestedGraph:
        mapping = require_mapping(value, "requested_graph")
        require_keys(mapping, {"schema_version", "parser_semantics_version"}, "requested_graph")
        return cls(
            require_literal_int(mapping["schema_version"], 1, "requested_graph.schema_version"),
            require_literal_int(mapping["parser_semantics_version"], 7, "requested_graph.parser_semantics_version"),
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "parser_semantics_version": self.parser_semantics_version,
        }


@dataclass(frozen=True)
class ParserStart:
    source_uri: str
    requested_graph: RequestedGraph

    def __post_init__(self) -> None:
        require_string(self.source_uri, "source_uri")
        if type(self.requested_graph) is not RequestedGraph:
            raise TypeError("requested_graph must be a RequestedGraph")

    @classmethod
    def from_mapping(cls, value: object) -> ParserStart:
        mapping = require_mapping(value, "payload")
        require_keys(mapping, {"source_uri", "requested_graph"}, "payload")
        return cls(
            require_string(mapping["source_uri"], "source_uri"),
            RequestedGraph.from_mapping(mapping["requested_graph"]),
        )

    def to_mapping(self) -> dict[str, object]:
        return {"source_uri": self.source_uri, "requested_graph": self.requested_graph.to_mapping()}
