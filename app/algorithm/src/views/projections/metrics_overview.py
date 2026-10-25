"""metrics.overview v1 whitelist projection."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from ..metrics_contract import metrics_view_fingerprint, population_metadata, validate_metrics_source_v1, validate_metrics_view_v1
from ..registry import metrics_profile_metadata


def _pick(source: Mapping[str, Any], names: tuple[str, ...]) -> dict[str, Any]:
    return {name: deepcopy(source[name]) for name in names}


def project_metrics_overview_v1(source: Mapping[str, Any]) -> dict[str, Any]:
    validate_metrics_source_v1(source)
    return _project_metrics_overview_v1(source)


def _project_metrics_overview_v1(source: Mapping[str, Any]) -> dict[str, Any]:
    metrics = source["metrics"]
    view = {
        "artifact_kind": "metrics_view", "view_schema_version": 1,
        "profile": {"id": "metrics.overview", "version": 1},
        "source": {"metrics_schema_version": source["schema_version"], "metrics_semantics_version": source["metrics_semantics_version"], "graph_schema_version": source["input"]["graph_schema_version"], "graph_fingerprint": source["input"]["graph_fingerprint"]},
        "completeness": metrics_profile_metadata("metrics.overview", 1),
        "payload": {
            "metrics": {
                "size": _pick(metrics["size"], ("directories", "files", "classes", "abstract_classes", "dataclasses", "functions", "methods", "fields", "constants")),
                "activity": _pick(metrics["activity"], ("calls", "local_imports", "external_imports", "average_calls_per_callable", "average_calls_per_call_owner", "average_methods_per_class")),
                "dependency_graph": _pick(metrics["dependency_graph"], ("nodes", "edges", "density", "average_fan_in", "average_fan_out", "weakly_connected_components")),
                "code_quality": _pick(metrics["code_quality"], ("analyzed_callables",)),
                "object_oriented": _pick(metrics["object_oriented"], ("classes_analyzed",)),
                "call_graph": _pick(metrics["call_graph"], ("nodes", "edges", "callsites_in_local_edges", "external_or_builtin_callsites", "unresolved_callsites", "unresolved_or_external_callsites", "local_resolution_rate", "classified_callsite_rate", "maximum_call_chain_depth", "maximum_syntactic_call_nesting")),
            },
            "population_metadata": population_metadata("metrics.overview"),
        },
        "view_fingerprint": "0" * 64,
    }
    view["view_fingerprint"] = metrics_view_fingerprint(view)
    validate_metrics_view_v1(view)
    return view


__all__ = ["project_metrics_overview_v1"]
