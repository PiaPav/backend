"""The inventory.minimal v1 occurrence-count summary projection."""
from __future__ import annotations

from typing import Any, Mapping

from graph_dto import validate_graph_v1

from ..registry import summary_profile_metadata
from ..summary_contract import graph_summary_fingerprint, validate_graph_summary_v1

_NODE_KINDS = ("class", "constant", "field", "file", "function", "method", "module")
_STATUSES = {
    "imports": ("exact", "external", "unresolved"),
    "types": ("ambiguous", "exact", "external", "unresolved"),
    "callsites": ("ambiguous", "dynamic", "exact", "external", "unresolved"),
}


def project_inventory_minimal_v1(source_graph: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and summarize a semantics-v7 canonical graph."""
    validate_graph_v1(source_graph)
    return _project_inventory_minimal_v1(source_graph)


def _project_inventory_minimal_v1(source_graph: Mapping[str, Any]) -> dict[str, Any]:
    """Summarize a source graph already validated by the public gateway."""
    if source_graph["schema_version"] != 1 or source_graph["parser_semantics_version"] != 7:
        raise ValueError("inventory.minimal v1 requires Graph DTO schema 1 / parser semantics 7")

    node_counts = {kind: 0 for kind in _NODE_KINDS}
    roots = []
    synthetic = 0
    for source in source_graph["nodes"]:
        kind = source["kind"]
        node_counts[kind] += 1
        if kind in {"file", "module"}:
            roots.append({key: source[key] for key in ("id", "kind", "qualified_name", "path")})
        if kind == "method" and source.get("synthetic") is True:
            synthetic += 1

    resolution_counts = {
        domain: {status: 0 for status in statuses}
        for domain, statuses in _STATUSES.items()
    }
    for collection, domain in (("import_references", "imports"), ("type_references", "types"), ("callsites", "callsites")):
        for occurrence in source_graph[collection]:
            resolution_counts[domain][occurrence["resolution"]] += 1

    diagnostic_counts: dict[tuple[str, str], int] = {}
    for diagnostic in source_graph["diagnostics"]:
        kind, status = diagnostic.get("kind"), diagnostic.get("status")
        if type(kind) is not str or not kind or type(status) is not str or not status:
            raise ValueError("inventory.minimal diagnostic kind/status must be non-empty strings")
        pair = (kind, status)
        diagnostic_counts[pair] = diagnostic_counts.get(pair, 0) + 1
    diagnostic_rows = [
        {"kind": kind, "status": status, "count": count}
        for (kind, status), count in sorted(diagnostic_counts.items())
    ]

    summary: dict[str, Any] = {
        "artifact_kind": "graph_summary",
        "summary_schema_version": 1,
        "profile": {"id": "inventory.minimal", "version": 1},
        "source": {
            "graph_schema_version": source_graph["schema_version"],
            "parser_semantics_version": source_graph["parser_semantics_version"],
            "graph_fingerprint": source_graph["project"]["fingerprint"],
        },
        "completeness": summary_profile_metadata("inventory.minimal", 1),
        "payload": {
            "roots": sorted(roots, key=lambda item: item["id"]),
            "node_counts": node_counts,
            "synthetic_method_count": synthetic,
            "diagnostics": {"total": len(source_graph["diagnostics"]), "by_kind_status": diagnostic_rows},
            "reference_resolution_counts": resolution_counts,
        },
        "summary_fingerprint": "0" * 64,
    }
    summary["summary_fingerprint"] = graph_summary_fingerprint(summary)
    validate_graph_summary_v1(summary)
    return summary


__all__ = ["project_inventory_minimal_v1"]
