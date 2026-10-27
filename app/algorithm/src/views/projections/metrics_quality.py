"""metrics.quality v1 whitelist projection."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from ..metrics_contract import THRESHOLD_POLICY, metrics_view_fingerprint, population_metadata, validate_metrics_source_v1, validate_metrics_view_v1
from ..registry import metrics_profile_metadata


def project_metrics_quality_v1(source: Mapping[str, Any]) -> dict[str, Any]:
    validate_metrics_source_v1(source)
    return _project_metrics_quality_v1(source)


def _project_metrics_quality_v1(source: Mapping[str, Any]) -> dict[str, Any]:
    metrics = source["metrics"]
    raw = metrics["code_quality"]
    quality = {name: deepcopy(raw[name]) for name in (
        "analyzed_callables", "average_cyclomatic_complexity", "average_cognitive_complexity",
        "average_lines_per_callable", "maximum_control_nesting",
    )}
    quality["high_complexity_callables"] = [
        {name: deepcopy(row[name]) for name in ("node", "cyclomatic", "cognitive", "lines", "nesting")}
        for row in raw["high_complexity_callables"]
    ]
    quality["largest_callables"] = [
        {name: deepcopy(row[name]) for name in ("node", "lines")}
        for row in raw["largest_callables"]
    ]
    quality["deeply_nested_callables"] = [
        {name: deepcopy(row[name]) for name in ("node", "nesting")}
        for row in raw["deeply_nested_callables"]
    ]
    quality["async"] = {name: deepcopy(raw["async"][name]) for name in ("functions", "without_await")}
    exceptions = raw["exceptions"]
    quality["exceptions"] = {
        name: deepcopy(exceptions[name])
        for name in ("raise_statements", "callables_raising", "raised_types", "caught_types")
    }
    quality["exceptions"]["broad_handlers"] = [
        {name: deepcopy(row[name]) for name in ("node", "count")}
        for row in exceptions["broad_handlers"]
    ]
    total = quality["analyzed_callables"]
    returned = len(quality["largest_callables"])
    view = {
        "artifact_kind": "metrics_view",
        "view_schema_version": 1,
        "profile": {"id": "metrics.quality", "version": 1},
        "source": {
            "metrics_schema_version": source["schema_version"],
            "metrics_semantics_version": source["metrics_semantics_version"],
            "graph_schema_version": source["input"]["graph_schema_version"],
            "graph_fingerprint": source["input"]["graph_fingerprint"],
        },
        "completeness": metrics_profile_metadata("metrics.quality", 1),
        "payload": {
            "metrics": {
                "size": {
                    "functions": deepcopy(metrics["size"]["functions"]),
                    "methods": deepcopy(metrics["size"]["methods"]),
                },
                "code_quality": quality,
            },
            "population_metadata": population_metadata("metrics.quality"),
            "threshold_policy": deepcopy(THRESHOLD_POLICY),
            "truncation_metadata": {
                "descriptor_version": 1,
                "rankings": {
                    "metrics.code_quality.largest_callables": {
                        "limit": 10,
                        "returned_count": returned,
                        "total_matching": total,
                        "truncated": total > returned,
                        "ordering": ["lines descending", "node ascending"],
                    }
                },
            },
        },
        "view_fingerprint": "0" * 64,
    }
    view["view_fingerprint"] = metrics_view_fingerprint(view)
    validate_metrics_view_v1(view)
    return view


__all__ = ["project_metrics_quality_v1"]
