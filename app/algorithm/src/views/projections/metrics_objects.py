"""metrics.objects v1 recursive-whitelist projection."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from ..metrics_contract import (
    OBJECT_INTERPRETATION_POLICY, OBJECT_TOPOLOGY_POLICY, metrics_view_fingerprint,
    population_metadata, validate_metrics_source_v1, validate_metrics_view_v1,
)
from ..registry import metrics_profile_metadata

_ROW_FIELDS = ("class", "wmc", "cbo", "rfc", "lcom", "dit", "noc")
_RANKINGS = (
    ("highest_weighted_method_complexity", "wmc"),
    ("highest_class_coupling", "cbo"),
    ("largest_response_sets", "rfc"),
    ("lowest_cohesion", "lcom"),
    ("deepest_inheritance", "dit"),
    ("most_direct_children", "noc"),
)


def _row(source: Mapping[str, Any]) -> dict[str, Any]:
    return {name: deepcopy(source[name]) for name in _ROW_FIELDS}


def project_metrics_objects_v1(source: Mapping[str, Any]) -> dict[str, Any]:
    validate_metrics_source_v1(source)
    return _project_metrics_objects_v1(source)


def _project_metrics_objects_v1(source: Mapping[str, Any]) -> dict[str, Any]:
    metrics = source["metrics"]
    raw = metrics["object_oriented"]
    objects = {"classes_analyzed": deepcopy(raw["classes_analyzed"])}
    for name, _ in _RANKINGS:
        objects[name] = [_row(row) for row in raw[name]]
    objects["classes"] = [_row(row) for row in raw["classes"]]

    rankings = {}
    for name, key in _RANKINGS:
        total = (sum(row[key] is not None for row in objects["classes"])
                 if key in {"lcom", "dit"} else objects["classes_analyzed"])
        returned = len(objects[name])
        rankings[f"metrics.object_oriented.{name}"] = {
            "limit": 10,
            "returned_count": returned,
            "total_matching": total,
            "truncated": total > returned,
            "ordering": [f"{key} descending", "class ascending"],
        }

    view = {
        "artifact_kind": "metrics_view",
        "view_schema_version": 1,
        "profile": {"id": "metrics.objects", "version": 1},
        "source": {
            "metrics_schema_version": source["schema_version"],
            "metrics_semantics_version": source["metrics_semantics_version"],
            "graph_schema_version": source["input"]["graph_schema_version"],
            "graph_fingerprint": source["input"]["graph_fingerprint"],
        },
        "completeness": metrics_profile_metadata("metrics.objects", 1),
        "payload": {
            "metrics": {
                "size": {name: deepcopy(metrics["size"][name])
                         for name in ("classes", "methods", "fields")},
                "object_oriented": objects,
            },
            "population_metadata": population_metadata("metrics.objects"),
            "topology_policy": deepcopy(OBJECT_TOPOLOGY_POLICY),
            "interpretation_policy": deepcopy(OBJECT_INTERPRETATION_POLICY),
            "truncation_metadata": {"descriptor_version": 1, "rankings": rankings},
        },
        "view_fingerprint": "0" * 64,
    }
    view["view_fingerprint"] = metrics_view_fingerprint(view)
    validate_metrics_view_v1(view)
    return view


__all__ = ["project_metrics_objects_v1"]
