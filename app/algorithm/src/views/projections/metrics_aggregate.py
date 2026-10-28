"""metrics.aggregate v1 exact scalar whitelist projection."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from ..metrics_contract import (
    AGGREGATE_POLICY, metrics_view_fingerprint, population_metadata,
    validate_metrics_source_v1, validate_metrics_view_v1,
)
from ..registry import METRICS_AGGREGATE_ID, METRICS_AGGREGATE_VERSION, metrics_profile_metadata


def _pick(source: Mapping[str, Any], names: tuple[str, ...]) -> dict[str, Any]:
    return {name: deepcopy(source[name]) for name in names}


def project_metrics_aggregate_v1(source: Mapping[str, Any]) -> dict[str, Any]:
    validate_metrics_source_v1(source)
    return _project_metrics_aggregate_v1(source)


def _project_metrics_aggregate_v1(source: Mapping[str, Any]) -> dict[str, Any]:
    metrics = source["metrics"]
    view = {
        "artifact_kind": "metrics_view", "view_schema_version": 1,
        "profile": {"id": METRICS_AGGREGATE_ID, "version": METRICS_AGGREGATE_VERSION},
        "source": {
            "metrics_schema_version": source["schema_version"],
            "metrics_semantics_version": source["metrics_semantics_version"],
            "graph_schema_version": source["input"]["graph_schema_version"],
            "graph_fingerprint": source["input"]["graph_fingerprint"],
        },
        "completeness": metrics_profile_metadata(METRICS_AGGREGATE_ID, METRICS_AGGREGATE_VERSION),
        "payload": {
            "metrics": {
                "size": _pick(metrics["size"], ("directories", "files", "classes", "abstract_classes", "dataclasses", "functions", "methods", "fields", "constants")),
                "activity": _pick(metrics["activity"], ("calls", "local_imports", "external_imports")),
                "dependency_graph": _pick(metrics["dependency_graph"], ("nodes", "edges", "weakly_connected_components")),
                "architecture": _pick(metrics["architecture"], ("package_edges",)),
                "code_quality": {
                    "analyzed_callables": deepcopy(metrics["code_quality"]["analyzed_callables"]),
                    "async": _pick(metrics["code_quality"]["async"], ("functions",)),
                    "exceptions": _pick(metrics["code_quality"]["exceptions"], ("raise_statements", "callables_raising")),
                },
                "object_oriented": _pick(metrics["object_oriented"], ("classes_analyzed",)),
                "call_graph": _pick(metrics["call_graph"], ("nodes", "edges", "callsites_in_local_edges", "external_or_builtin_callsites", "unresolved_callsites", "unresolved_or_external_callsites")),
            },
            "population_metadata": population_metadata(METRICS_AGGREGATE_ID),
            "aggregate_policy": deepcopy(AGGREGATE_POLICY),
        },
        "view_fingerprint": "0" * 64,
    }
    view["view_fingerprint"] = metrics_view_fingerprint(view)
    validate_metrics_view_v1(view)
    return view


__all__ = ["project_metrics_aggregate_v1"]
