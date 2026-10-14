"""Pure normalization, hashing and validation for Graph DTO v1."""
from __future__ import annotations

import hashlib
import json
from pathlib import PurePosixPath
from typing import Any, Mapping

NODE_KINDS = frozenset({"file", "module", "class", "function", "method"})
EDGE_KINDS = frozenset({"contains", "imports", "inherits", "calls", "awaits"})
RESOLUTION_STATUSES = frozenset({"exact", "ambiguous", "external", "dynamic", "unresolved"})
_COLLECTIONS = ("nodes", "edges", "callsites", "diagnostics")


def _key(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonicalize_graph(graph: Mapping[str, Any]) -> dict[str, Any]:
    """Return canonical DTO content; transitional ``body`` is never canonical."""
    result = {key: value for key, value in graph.items() if key != "body"}
    project = dict(result.get("project", {}))
    project.pop("fingerprint", None)
    result["project"] = project
    for name in _COLLECTIONS:
        result[name] = sorted((dict(item) for item in result.get(name, [])), key=_key)
    return result


def graph_fingerprint(graph: Mapping[str, Any]) -> str:
    payload = json.dumps(canonicalize_graph(graph), ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _error(message: str) -> None:
    raise ValueError(f"Invalid Graph DTO v1: {message}")


def _relative_path(value: Any, where: str) -> None:
    if not isinstance(value, str) or not value or "\\" in value:
        _error(f"{where} must be a relative POSIX path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        _error(f"{where} must be a relative POSIX path")


def _location(value: Any, where: str) -> None:
    if not isinstance(value, Mapping):
        _error(f"{where} must be an object")
    _relative_path(value.get("path"), f"{where}.path")
    if type(value.get("line")) is not int or value["line"] < 1:
        _error(f"{where}.line is invalid")
    if type(value.get("column")) is not int or value["column"] < 0:
        _error(f"{where}.column is invalid")


def validate_graph_v1(graph: Mapping[str, Any], *, verify_fingerprint: bool = True) -> None:
    if not isinstance(graph, Mapping):
        _error("root must be an object")
    if type(graph.get("schema_version")) is not int or graph["schema_version"] != 1:
        _error(f"Unsupported schema_version {graph.get('schema_version')!r}")
    if type(graph.get("parser_semantics_version")) is not int or graph["parser_semantics_version"] != 1:
        _error(f"Unsupported parser_semantics_version {graph.get('parser_semantics_version')!r}")
    project = graph.get("project")
    if not isinstance(project, Mapping) or not isinstance(project.get("fingerprint"), str):
        _error("project.fingerprint is required")
    for name in _COLLECTIONS:
        if not isinstance(graph.get(name), list):
            _error(f"{name} must be an array")
    nodes: dict[str, Mapping[str, Any]] = {}
    for index, node in enumerate(graph["nodes"]):
        if not isinstance(node, Mapping): _error(f"nodes[{index}] must be an object")
        identifier = node.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in nodes:
            _error(f"nodes[{index}].id is missing or duplicate")
        if node.get("kind") not in NODE_KINDS: _error(f"nodes[{index}].kind is invalid")
        if not isinstance(node.get("qualified_name"), str): _error(f"nodes[{index}].qualified_name is required")
        _relative_path(node.get("path"), f"nodes[{index}].path")
        _location(node.get("location"), f"nodes[{index}].location")
        if node.get("kind") == "file" and identifier != f"file:{node.get('path')}":
            _error(f"nodes[{index}] file id must equal 'file:<path>'")
        nodes[identifier] = node
    contains: dict[str, str] = {}
    seen_edge_ids: set[str] = set()
    call_weights: dict[tuple[str, str, str], int] = {}
    for index, edge in enumerate(graph["edges"]):
        if not isinstance(edge, Mapping): _error(f"edges[{index}] must be an object")
        edge_id = edge.get("id")
        if not isinstance(edge_id, str) or not edge_id or edge_id in seen_edge_ids:
            _error(f"edges[{index}].id is missing or duplicate")
        seen_edge_ids.add(edge_id)
        kind, source, target = edge.get("kind"), edge.get("source_id"), edge.get("target_id")
        if kind not in EDGE_KINDS: _error(f"edges[{index}].kind is invalid")
        if source not in nodes or target not in nodes: _error(f"edges[{index}] has an unknown node reference")
        if kind == "contains":
            if target in contains: _error(f"node {target!r} has multiple containers")
            contains[target] = source
        if "location" in edge:
            _location(edge["location"], f"edges[{index}].location")
        if kind in {"calls", "awaits"}:
            if nodes[source]["kind"] not in {"file", "module", "function", "method"}:
                _error(f"edges[{index}] {kind} source must be a call owner")
            if nodes[target]["kind"] not in {"function", "method"}:
                _error(f"edges[{index}] {kind} target must be a callable node")
            if "weight" not in edge:
                _error(f"edges[{index}].weight is required for {kind}")
            weight = edge["weight"]
            if not isinstance(weight, int) or isinstance(weight, bool) or weight < 1: _error(f"edges[{index}].weight is invalid")
            key = (source, target, kind)
            if key in call_weights:
                _error(f"edges[{index}] duplicates an aggregated {kind} edge")
            call_weights[key] = weight
    for node in nodes:
        seen: set[str] = set()
        current = node
        while current in contains:
            if current in seen: _error("contains edges must form an acyclic forest")
            seen.add(current); current = contains[current]
        parent = nodes[node].get("parent_id")
        if parent is not None and parent not in nodes:
            _error(f"node {node!r} has an unknown parent_id")
        if parent != contains.get(node):
            _error(f"node {node!r} parent_id is inconsistent with contains edges")
        if nodes[node]["kind"] in {"function", "method"} and parent is None:
            _error(f"callable node {node!r} must have exactly one owner")
    observed: dict[tuple[str, str, str], int] = {}
    seen_callsites: set[str] = set()
    for index, callsite in enumerate(graph["callsites"]):
        if not isinstance(callsite, Mapping): _error(f"callsites[{index}] must be an object")
        identifier, caller, status = callsite.get("id"), callsite.get("caller_id"), callsite.get("resolution")
        if not isinstance(identifier, str) or not identifier or identifier in seen_callsites: _error(f"callsites[{index}].id is missing or duplicate")
        seen_callsites.add(identifier)
        if caller not in nodes: _error(f"callsites[{index}].caller_id is invalid")
        if nodes[caller]["kind"] not in {"file", "module", "function", "method"}:
            _error(f"callsites[{index}].caller_id must reference a call owner node")
        if not isinstance(callsite.get("expression"), str) or not callsite["expression"]:
            _error(f"callsites[{index}].expression is required")
        _location(callsite.get("location"), f"callsites[{index}].location")
        depth = callsite.get("syntactic_depth")
        if not isinstance(depth, int) or isinstance(depth, bool) or depth < 0:
            _error(f"callsites[{index}].syntactic_depth is invalid")
        if status not in RESOLUTION_STATUSES: _error(f"callsites[{index}].resolution is invalid")
        if type(callsite.get("awaited")) is not bool:
            _error(f"callsites[{index}].awaited must be a boolean")
        target, candidates = callsite.get("target_id"), callsite.get("candidate_ids", [])
        if not isinstance(candidates, list) or candidates != sorted(candidates) or len(candidates) != len(set(candidates)):
            _error(f"callsites[{index}].candidate_ids must be unique and sorted")
        if any(item not in nodes for item in candidates): _error(f"callsites[{index}] has an unknown candidate")
        if any(nodes[item]["kind"] not in {"function", "method"} for item in candidates):
            _error(f"callsites[{index}].candidate_ids must reference callable nodes")
        if status == "exact":
            if target not in nodes or candidates: _error(f"callsites[{index}] exact resolution requires exactly target_id")
            if nodes[target]["kind"] not in {"function", "method"}:
                _error(f"callsites[{index}].target_id must reference a callable node")
            kind = "awaits" if callsite.get("awaited") is True else "calls"
            observed[(caller, target, kind)] = observed.get((caller, target, kind), 0) + 1
        elif status == "ambiguous":
            if target is not None or len(candidates) < 2: _error(f"callsites[{index}] ambiguous resolution requires >=2 candidates")
        elif target is not None or candidates:
            _error(f"callsites[{index}] non-internal resolution cannot have targets")
    if call_weights != observed:
        _error("aggregated call edge weights do not match exact callsites")
    diagnostic_ids: set[str] = set()
    for index, diagnostic in enumerate(graph["diagnostics"]):
        if not isinstance(diagnostic, Mapping): _error(f"diagnostics[{index}] must be an object")
        identifier = diagnostic.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in diagnostic_ids:
            _error(f"diagnostics[{index}].id is missing or duplicate")
        diagnostic_ids.add(identifier)
    if verify_fingerprint and project["fingerprint"] != graph_fingerprint(graph):
        _error("project.fingerprint does not match canonical content")
