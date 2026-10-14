"""Declarative Graph DTO v1 contract shared by parser and metrics."""

from .contract import (
    EDGE_KINDS,
    NODE_KINDS,
    RESOLUTION_STATUSES,
    canonicalize_graph,
    graph_fingerprint,
    validate_graph_v1,
)

SCHEMA_VERSION = 1
PARSER_SEMANTICS_VERSION = 1

__all__ = [
    "EDGE_KINDS", "NODE_KINDS", "PARSER_SEMANTICS_VERSION",
    "RESOLUTION_STATUSES", "SCHEMA_VERSION", "canonicalize_graph",
    "graph_fingerprint", "validate_graph_v1",
]
