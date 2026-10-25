"""metrics.architecture v1 whitelist projection."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from ..metrics_contract import PACKAGE_GROUPING, metrics_view_fingerprint, population_metadata, validate_metrics_source_v1, validate_metrics_view_v1
from ..registry import metrics_profile_metadata


def _pick(source: Mapping[str, Any], names: tuple[str, ...]) -> dict[str, Any]:
    return {name: deepcopy(source[name]) for name in names}


def project_metrics_architecture_v1(source: Mapping[str, Any]) -> dict[str, Any]:
    validate_metrics_source_v1(source)
    return _project_metrics_architecture_v1(source)


def _project_metrics_architecture_v1(source: Mapping[str, Any]) -> dict[str, Any]:
    metrics = source["metrics"]
    dependency = _pick(metrics["dependency_graph"], ("nodes", "edges", "density", "average_fan_in", "average_fan_out", "weakly_connected_components", "isolated_files", "cyclic_components"))
    for name in ("highest_fan_in", "highest_fan_out"):
        dependency[name] = _pick(metrics["dependency_graph"][name], ("degree", "files"))
    architecture = _pick(metrics["architecture"], ("package_edges", "cyclic_package_components", "articulation_files", "bridge_dependencies"))
    package_fields = ("package", "files", "classes", "abstract_classes", "afferent_coupling", "efferent_coupling", "instability", "abstractness", "distance_from_main_sequence")
    architecture["packages"] = [_pick(row, package_fields) for row in metrics["architecture"]["packages"]]
    view = {
        "artifact_kind": "metrics_view", "view_schema_version": 1,
        "profile": {"id": "metrics.architecture", "version": 1},
        "source": {"metrics_schema_version": source["schema_version"], "metrics_semantics_version": source["metrics_semantics_version"], "graph_schema_version": source["input"]["graph_schema_version"], "graph_fingerprint": source["input"]["graph_fingerprint"]},
        "completeness": metrics_profile_metadata("metrics.architecture", 1),
        "payload": {
            "metrics": {
                "activity": _pick(metrics["activity"], ("local_imports", "external_imports")),
                "dependency_graph": dependency,
                "architecture": architecture,
            },
            "population_metadata": population_metadata("metrics.architecture"),
            "package_grouping": deepcopy(PACKAGE_GROUPING),
        },
        "view_fingerprint": "0" * 64,
    }
    view["view_fingerprint"] = metrics_view_fingerprint(view)
    validate_metrics_view_v1(view)
    return view


__all__ = ["project_metrics_architecture_v1"]
