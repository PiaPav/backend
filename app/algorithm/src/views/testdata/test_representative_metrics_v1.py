"""Deterministic full Metrics DTO envelopes derived from graph benchmark v2."""
from __future__ import annotations

from typing import Any

from metrics import calculate_graph_metrics
from views.testdata.representative_graph_v2 import build_representative_graph_v2


def build_representative_metrics_v1(size: str) -> dict[str, Any]:
    """Build a complete Metrics DTO, retaining exact graph provenance."""
    graph = build_representative_graph_v2(size)
    return {
        "schema_version": 1,
        "metrics_semantics_version": 4,
        "input": {
            "graph_schema_version": graph["schema_version"],
            "graph_fingerprint": graph["project"]["fingerprint"],
        },
        "metrics": calculate_graph_metrics(graph),
    }


__all__ = ["build_representative_metrics_v1"]
