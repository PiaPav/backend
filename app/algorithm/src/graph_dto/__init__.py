"""Declarative Graph DTO v1 contract shared by parser and metrics."""

from .contract import (
    CLASS_KINDS,
    EDGE_KINDS,
    IMPORT_RESOLUTION_STATUSES,
    CONTROL_KINDS,
    NODE_KINDS,
    OCCURRENCE_KINDS,
    RESOLUTION_STATUSES,
    canonicalize_graph,
    graph_fingerprint,
    validate_graph_v1,
)

SCHEMA_VERSION = 1
PARSER_SEMANTICS_VERSION = 7

__all__ = [
    "CLASS_KINDS", "CONTROL_KINDS", "EDGE_KINDS", "IMPORT_RESOLUTION_STATUSES", "NODE_KINDS", "OCCURRENCE_KINDS", "PARSER_SEMANTICS_VERSION",
    "RESOLUTION_STATUSES", "SCHEMA_VERSION", "canonicalize_graph",
    "graph_fingerprint", "validate_graph_v1",
]
