"""Standalone validation, hashing and serialization for Graph View DTO v1."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import PurePosixPath
from typing import Any, Mapping

from graph_dto import CLASS_KINDS, NODE_KINDS

from .registry import profile_metadata

_HEX_64 = re.compile(r"[0-9a-f]{64}\Z")
_ROOT_KEYS = {
    "artifact_kind", "view_schema_version", "profile", "source",
    "completeness", "payload", "view_fingerprint",
}
_NODE_REQUIRED = {"id", "kind", "qualified_name", "parent_id", "path"}
_EDGE_KEYS = {"id", "kind", "source_id", "target_id"}


def _error(message: str) -> None:
    raise ValueError(f"Invalid Graph View DTO v1: {message}")


def _object(value: Any, keys: set[str], where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _error(f"{where} must be an object")
    if set(value) != keys:
        _error(f"{where} has invalid fields")
    return value


def _relative_path(value: Any, where: str) -> None:
    if not isinstance(value, str) or not value or "\\" in value:
        _error(f"{where} must be a relative POSIX path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        _error(f"{where} must be a relative POSIX path")


def _compact_content(view: Mapping[str, Any]) -> bytes:
    content = {key: value for key, value in view.items() if key != "view_fingerprint"}
    payload = content.get("payload")
    if isinstance(payload, Mapping):
        content["payload"] = dict(payload)
        for name in ("nodes", "edges"):
            values = payload.get(name)
            if isinstance(values, list):
                content["payload"][name] = sorted(
                    values,
                    key=lambda item: item.get("id", "") if isinstance(item, Mapping) else "",
                )
    return json.dumps(
        content, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def graph_view_fingerprint(view: Mapping[str, Any]) -> str:
    """Hash the complete envelope except its top-level fingerprint field."""
    if not isinstance(view, Mapping):
        _error("root must be an object")
    return hashlib.sha256(_compact_content(view)).hexdigest()


def validate_graph_view_v1(
    view: Mapping[str, Any], *, verify_fingerprint: bool = True
) -> None:
    """Strictly validate a supported Graph View DTO without Parser or Metrics."""
    root = _object(view, _ROOT_KEYS, "root")
    if root.get("artifact_kind") != "graph_view":
        _error("artifact_kind must be 'graph_view'")
    if type(root.get("view_schema_version")) is not int or root["view_schema_version"] != 1:
        _error(f"Unsupported view_schema_version {root.get('view_schema_version')!r}")

    profile = _object(root.get("profile"), {"id", "version"}, "profile")
    expected_completeness = profile_metadata(profile.get("id"), profile.get("version"))
    source = _object(
        root.get("source"),
        {"graph_schema_version", "parser_semantics_version", "graph_fingerprint"},
        "source",
    )
    for field, expected in (("graph_schema_version", 1), ("parser_semantics_version", 7)):
        if type(source.get(field)) is not int or source[field] != expected:
            _error(f"Unsupported source {field} {source.get(field)!r}")
    if not isinstance(source.get("graph_fingerprint"), str) or not _HEX_64.fullmatch(source["graph_fingerprint"]):
        _error("source.graph_fingerprint must be lowercase SHA-256 hex")

    completeness = _object(root.get("completeness"), {"kind", "preserves", "omits"}, "completeness")
    if completeness != expected_completeness:
        _error("completeness does not match profile registry metadata")
    if any(not isinstance(completeness[name], list) for name in ("preserves", "omits")):
        _error("completeness preserves and omits must be arrays")
    if any(values != sorted(values) for values in (completeness["preserves"], completeness["omits"])):
        _error("completeness lists must be lexicographically sorted")

    payload = _object(root.get("payload"), {"nodes", "edges"}, "payload")
    if not isinstance(payload["nodes"], list) or not isinstance(payload["edges"], list):
        _error("payload nodes and edges must be arrays")
    nodes: dict[str, Mapping[str, Any]] = {}
    node_ids: list[str] = []
    for index, value in enumerate(payload["nodes"]):
        where = f"payload.nodes[{index}]"
        if not isinstance(value, Mapping):
            _error(f"{where} must be an object")
        kind = value.get("kind")
        allowed = _NODE_REQUIRED | ({"class_kind"} if kind == "class" else set())
        if kind == "method" and value.get("synthetic") is True:
            allowed.add("synthetic")
        if set(value) != allowed:
            _error(f"{where} has invalid fields")
        identifier = value.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in nodes:
            _error(f"{where}.id is missing or duplicate")
        if kind not in NODE_KINDS:
            _error(f"{where}.kind is invalid")
        if not isinstance(value.get("qualified_name"), str):
            _error(f"{where}.qualified_name must be a string")
        parent = value.get("parent_id")
        if parent is not None and (not isinstance(parent, str) or not parent):
            _error(f"{where}.parent_id is invalid")
        _relative_path(value.get("path"), f"{where}.path")
        if kind == "class" and value.get("class_kind") not in CLASS_KINDS:
            _error(f"{where}.class_kind is invalid")
        if "synthetic" in value and (kind != "method" or value["synthetic"] is not True):
            _error(f"{where}.synthetic is only allowed as true on methods")
        nodes[identifier] = value
        node_ids.append(identifier)
    if node_ids != sorted(node_ids):
        _error("payload.nodes must have unique lexicographically sorted IDs")

    owners: dict[str, str] = {}
    edge_ids: list[str] = []
    for index, value in enumerate(payload["edges"]):
        where = f"payload.edges[{index}]"
        edge = _object(value, _EDGE_KEYS, where)
        identifier = edge.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in edge_ids:
            _error(f"{where}.id is missing or duplicate")
        edge_ids.append(identifier)
        if edge.get("kind") != "contains":
            _error(f"{where}.kind must be 'contains'")
        source_id, target_id = edge.get("source_id"), edge.get("target_id")
        if source_id not in nodes or target_id not in nodes:
            _error(f"{where} has a dangling endpoint")
        if target_id in owners:
            _error(f"node {target_id!r} has multiple containers")
        owners[target_id] = source_id
    if edge_ids != sorted(edge_ids):
        _error("payload.edges must have unique lexicographically sorted IDs")

    for identifier, node in nodes.items():
        parent = node["parent_id"]
        if parent is not None and parent not in nodes:
            _error(f"node {identifier!r} has a dangling parent_id")
        if parent != owners.get(identifier):
            _error(f"node {identifier!r} parent_id is inconsistent with contains edges")
        seen: set[str] = set()
        current = identifier
        while current in owners:
            if current in seen:
                _error("contains edges must form an acyclic forest")
            seen.add(current)
            current = owners[current]
        if node["kind"] in {"file", "module"}:
            if parent is not None:
                _error(f"canonical root node {identifier!r} must not have a parent")
        elif parent is None:
            _error(f"declaration node {identifier!r} must have exactly one owner")
        expected_owner = {
            "class": {"file", "module"}, "function": {"file", "module"},
            "constant": {"file", "module"}, "method": {"class"}, "field": {"class"},
        }.get(node["kind"])
        if expected_owner is not None and nodes[parent]["kind"] not in expected_owner:
            _error(f"node {identifier!r} has an invalid owner")

    fingerprint = root.get("view_fingerprint")
    if not isinstance(fingerprint, str) or not _HEX_64.fullmatch(fingerprint):
        _error("view_fingerprint must be lowercase SHA-256 hex")
    if verify_fingerprint and fingerprint != graph_view_fingerprint(root):
        _error("view_fingerprint does not match canonical content")


def serialize_graph_view(view: Mapping[str, Any]) -> bytes:
    """Validate and serialize a Graph View as deterministic pretty UTF-8 JSON."""
    validate_graph_view_v1(view)
    text = json.dumps(view, ensure_ascii=False, sort_keys=True, indent=2)
    return (text + "\n").encode("utf-8")


__all__ = ["graph_view_fingerprint", "serialize_graph_view", "validate_graph_view_v1"]
