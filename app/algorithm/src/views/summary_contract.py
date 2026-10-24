"""Standalone contract for the inventory Graph Summary DTO v1."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import PurePosixPath
from typing import Any, Mapping

from .registry import summary_profile_metadata

_HEX_64 = re.compile(r"[0-9a-f]{64}\Z")
_NODE_KINDS = ("class", "constant", "field", "file", "function", "method", "module")
_STATUSES = {
    "imports": ("exact", "external", "unresolved"),
    "types": ("ambiguous", "exact", "external", "unresolved"),
    "callsites": ("ambiguous", "dynamic", "exact", "external", "unresolved"),
}


def _error(message: str) -> None:
    raise ValueError(f"Invalid Graph Summary DTO v1: {message}")


def _object(value: Any, keys: set[str], where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        _error(f"{where} must be an object with exact fields")
    return value


def _compact_content(summary: Mapping[str, Any]) -> bytes:
    content = {key: value for key, value in summary.items() if key != "summary_fingerprint"}
    payload = content.get("payload")
    if isinstance(payload, Mapping):
        content["payload"] = dict(payload)
        roots = payload.get("roots")
        if isinstance(roots, list):
            content["payload"]["roots"] = sorted(
                roots, key=lambda item: item.get("id", "") if isinstance(item, Mapping) else ""
            )
        diagnostics = payload.get("diagnostics")
        if isinstance(diagnostics, Mapping):
            content["payload"]["diagnostics"] = dict(diagnostics)
            rows = diagnostics.get("by_kind_status")
            if isinstance(rows, list):
                content["payload"]["diagnostics"]["by_kind_status"] = sorted(
                    rows, key=lambda item: (item.get("kind", ""), item.get("status", ""))
                    if isinstance(item, Mapping) else ("", "")
                )
    return json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def graph_summary_fingerprint(summary: Mapping[str, Any]) -> str:
    if not isinstance(summary, Mapping):
        _error("root must be an object")
    return hashlib.sha256(_compact_content(summary)).hexdigest()


def _count(value: Any, where: str, *, positive: bool = False) -> int:
    if type(value) is not int or value < (1 if positive else 0):
        _error(f"{where} must be a {'positive' if positive else 'non-negative'} integer")
    return value


def validate_graph_summary_v1(summary: Mapping[str, Any], *, verify_fingerprint: bool = True) -> None:
    root = _object(summary, {"artifact_kind", "summary_schema_version", "profile", "source", "completeness", "payload", "summary_fingerprint"}, "root")
    if root["artifact_kind"] != "graph_summary":
        _error("artifact_kind must be 'graph_summary'")
    if type(root["summary_schema_version"]) is not int or root["summary_schema_version"] != 1:
        _error("summary_schema_version must be 1")
    profile = _object(root["profile"], {"id", "version"}, "profile")
    expected = summary_profile_metadata(profile.get("id"), profile.get("version"))
    source = _object(root["source"], {"graph_schema_version", "parser_semantics_version", "graph_fingerprint"}, "source")
    if type(source["graph_schema_version"]) is not int or source["graph_schema_version"] != 1:
        _error("source graph_schema_version must be 1")
    if type(source["parser_semantics_version"]) is not int or source["parser_semantics_version"] != 7:
        _error("source parser_semantics_version must be 7")
    if not isinstance(source["graph_fingerprint"], str) or not _HEX_64.fullmatch(source["graph_fingerprint"]):
        _error("source.graph_fingerprint must be lowercase SHA-256 hex")
    completeness = _object(root["completeness"], {"kind", "preserves", "omits"}, "completeness")
    if completeness != expected or any(not isinstance(completeness[k], list) for k in ("preserves", "omits")):
        _error("completeness does not match profile registry metadata")

    payload = _object(root["payload"], {"roots", "node_counts", "synthetic_method_count", "diagnostics", "reference_resolution_counts"}, "payload")
    roots = payload["roots"]
    if not isinstance(roots, list):
        _error("payload.roots must be an array")
    ids = []
    for index, value in enumerate(roots):
        item = _object(value, {"id", "kind", "qualified_name", "path"}, f"payload.roots[{index}]")
        if not isinstance(item["id"], str) or not item["id"]:
            _error(f"payload.roots[{index}].id must be non-empty")
        if item["kind"] not in {"file", "module"} or not isinstance(item["qualified_name"], str):
            _error(f"payload.roots[{index}] descriptor is invalid")
        path = item["path"]
        if not isinstance(path, str) or not path or "\\" in path or PurePosixPath(path).is_absolute() or any(part in {"", ".", ".."} for part in PurePosixPath(path).parts):
            _error(f"payload.roots[{index}].path must be a relative POSIX path")
        ids.append(item["id"])
    if ids != sorted(set(ids)):
        _error("payload.roots must have unique lexicographically sorted IDs")

    counts = _object(payload["node_counts"], set(_NODE_KINDS), "payload.node_counts")
    for kind in _NODE_KINDS:
        _count(counts[kind], f"payload.node_counts.{kind}")
    synthetic = _count(payload["synthetic_method_count"], "payload.synthetic_method_count")
    if len(roots) != counts["file"] + counts["module"] or synthetic > counts["method"]:
        _error("payload node/root count invariants are violated")
    resolutions = _object(payload["reference_resolution_counts"], set(_STATUSES), "payload.reference_resolution_counts")
    for domain, statuses in _STATUSES.items():
        buckets = _object(resolutions[domain], set(statuses), f"payload.reference_resolution_counts.{domain}")
        for status in statuses:
            _count(buckets[status], f"payload.reference_resolution_counts.{domain}.{status}")

    diagnostics = _object(payload["diagnostics"], {"total", "by_kind_status"}, "payload.diagnostics")
    total = _count(diagnostics["total"], "payload.diagnostics.total")
    rows = diagnostics["by_kind_status"]
    if not isinstance(rows, list):
        _error("payload.diagnostics.by_kind_status must be an array")
    pairs = []
    row_total = 0
    for index, value in enumerate(rows):
        row = _object(value, {"kind", "status", "count"}, f"payload.diagnostics.by_kind_status[{index}]")
        if any(not isinstance(row[key], str) or not row[key] for key in ("kind", "status")):
            _error(f"payload.diagnostics.by_kind_status[{index}] strings must be non-empty")
        pairs.append((row["kind"], row["status"]))
        row_total += _count(row["count"], f"payload.diagnostics.by_kind_status[{index}].count", positive=True)
    if pairs != sorted(set(pairs)) or row_total != total:
        _error("payload diagnostics ordering/count invariant is violated")
    fingerprint = root["summary_fingerprint"]
    if not isinstance(fingerprint, str) or not _HEX_64.fullmatch(fingerprint):
        _error("summary_fingerprint must be lowercase SHA-256 hex")
    if verify_fingerprint and fingerprint != graph_summary_fingerprint(root):
        _error("summary_fingerprint does not match canonical content")


def serialize_graph_summary(summary: Mapping[str, Any]) -> bytes:
    validate_graph_summary_v1(summary)
    return (json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


__all__ = ["graph_summary_fingerprint", "serialize_graph_summary", "validate_graph_summary_v1"]
