"""Standalone validation, hashing and serialization for Graph View DTO v1."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import PurePosixPath
from typing import Any, Mapping

from graph_dto import CLASS_KINDS, NODE_KINDS

from .registry import profile_metadata
from .metrics_contract import PACKAGE_GROUPING

_HEX_64 = re.compile(r"[0-9a-f]{64}\Z")
_ROOT_KEYS = {
    "artifact_kind", "view_schema_version", "profile", "source",
    "completeness", "payload", "view_fingerprint",
}
_NODE_REQUIRED = {"id", "kind", "qualified_name", "parent_id", "path"}
_EDGE_KEYS = {"id", "kind", "source_id", "target_id"}
_DEPENDENCY_NODE_KEYS = {"id", "kind", "qualified_name", "path"}
_DEPENDENCY_EDGE_KEYS = _EDGE_KEYS | {"exact_occurrence_count"}


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
        for name in ("nodes", "edges", "import_references"):
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


def aggregate_import_edge_id(source_id: str, target_id: str) -> str:
    """Return the normative ID for one aggregate import endpoint pair."""
    pair = json.dumps(
        [source_id, target_id], ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return f"aggregate:imports:{hashlib.sha256(pair).hexdigest()}"


def _validate_dependency_files(payload: Mapping[str, Any]) -> None:
    payload = _object(payload, {"nodes", "edges", "import_resolution_counts"}, "payload")
    if not isinstance(payload["nodes"], list) or not isinstance(payload["edges"], list):
        _error("payload nodes and edges must be arrays")
    nodes: dict[str, Mapping[str, Any]] = {}
    node_ids: list[str] = []
    for index, value in enumerate(payload["nodes"]):
        where = f"payload.nodes[{index}]"
        node = _object(value, _DEPENDENCY_NODE_KEYS, where)
        identifier = node.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in nodes:
            _error(f"{where}.id is missing or duplicate")
        if node.get("kind") not in {"file", "module"}:
            _error(f"{where}.kind must be 'file' or 'module'")
        if not isinstance(node.get("qualified_name"), str):
            _error(f"{where}.qualified_name must be a string")
        _relative_path(node.get("path"), f"{where}.path")
        nodes[identifier] = node
        node_ids.append(identifier)
    if node_ids != sorted(node_ids):
        _error("payload.nodes must have unique lexicographically sorted IDs")

    edge_ids: list[str] = []
    pairs: set[tuple[str, str]] = set()
    total = 0
    for index, value in enumerate(payload["edges"]):
        where = f"payload.edges[{index}]"
        edge = _object(value, _DEPENDENCY_EDGE_KEYS, where)
        identifier = edge.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in edge_ids or identifier in nodes:
            _error(f"{where}.id is missing or duplicate")
        if edge.get("kind") != "imports":
            _error(f"{where}.kind must be 'imports'")
        source_id, target_id = edge.get("source_id"), edge.get("target_id")
        if source_id not in nodes or target_id not in nodes:
            _error(f"{where} has a dangling endpoint")
        pair = (source_id, target_id)
        if pair in pairs:
            _error(f"{where} duplicates an ordered endpoint pair")
        pairs.add(pair)
        if identifier != aggregate_import_edge_id(source_id, target_id):
            _error(f"{where}.id does not match aggregate endpoint pair")
        count = edge.get("exact_occurrence_count")
        if type(count) is not int or count <= 0:
            _error(f"{where}.exact_occurrence_count must be a positive integer")
        total += count
        edge_ids.append(identifier)
    if edge_ids != sorted(edge_ids):
        _error("payload.edges must have unique lexicographically sorted IDs")
    counts = _object(
        payload["import_resolution_counts"], {"exact", "external", "unresolved"},
        "payload.import_resolution_counts",
    )
    if any(type(value) is not int or value < 0 for value in counts.values()):
        _error("import resolution counts must be nonnegative integers")
    if total != counts["exact"]:
        _error("aggregate import edge counts must equal exact resolution count")


def _validate_dependency_architecture(payload: Mapping[str, Any]) -> None:
    payload = _object(payload, {"nodes", "edges", "import_references", "import_resolution_counts", "package_grouping"}, "payload")
    if not all(isinstance(payload[name], list) for name in ("nodes", "edges", "import_references")):
        _error("payload nodes, edges and import_references must be arrays")
    if payload["package_grouping"] != PACKAGE_GROUPING:
        _error("package_grouping does not match static contract")
    nodes: dict[str, Mapping[str, Any]] = {}
    node_ids: list[str] = []
    for index, value in enumerate(payload["nodes"]):
        where = f"payload.nodes[{index}]"
        if not isinstance(value, Mapping):
            _error(f"{where} must be an object")
        kind = value.get("kind")
        keys = _DEPENDENCY_NODE_KEYS if kind in {"file", "module"} else _DEPENDENCY_NODE_KEYS | {"parent_id", "class_kind"}
        node = _object(value, keys, where)
        identifier = node.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in nodes:
            _error(f"{where}.id is missing or duplicate")
        if kind not in {"file", "module", "class"}:
            _error(f"{where}.kind is invalid")
        if not isinstance(node.get("qualified_name"), str):
            _error(f"{where}.qualified_name must be a string")
        _relative_path(node.get("path"), f"{where}.path")
        if kind == "class":
            if node.get("class_kind") not in CLASS_KINDS:
                _error(f"{where}.class_kind is invalid")
            if not isinstance(node.get("parent_id"), str) or not node["parent_id"]:
                _error(f"{where}.parent_id is invalid")
        nodes[identifier] = node; node_ids.append(identifier)
    if node_ids != sorted(node_ids):
        _error("payload.nodes must have unique lexicographically sorted IDs")

    owners: dict[str, str] = {}
    pairs: dict[tuple[str, str], int] = {}
    edge_ids: list[str] = []
    for index, value in enumerate(payload["edges"]):
        where = f"payload.edges[{index}]"
        if not isinstance(value, Mapping): _error(f"{where} must be an object")
        kind = value.get("kind")
        edge = _object(value, _EDGE_KEYS if kind == "contains" else _DEPENDENCY_EDGE_KEYS, where)
        identifier = edge.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in edge_ids or identifier in nodes:
            _error(f"{where}.id is missing or duplicate")
        source, target = edge.get("source_id"), edge.get("target_id")
        if source not in nodes or target not in nodes: _error(f"{where} has a dangling endpoint")
        if kind == "contains":
            if nodes[source]["kind"] not in {"file", "module"} or nodes[target]["kind"] != "class":
                _error(f"{where} must directly contain a class in a root")
            if target in owners: _error(f"node {target!r} has multiple containers")
            owners[target] = source
        elif kind == "imports":
            if nodes[source]["kind"] not in {"file", "module"} or nodes[target]["kind"] not in {"file", "module"}:
                _error(f"{where} imports endpoints must be roots")
            pair = (source, target)
            if pair in pairs: _error(f"{where} duplicates an ordered endpoint pair")
            if identifier != aggregate_import_edge_id(source, target): _error(f"{where}.id does not match aggregate endpoint pair")
            count = edge.get("exact_occurrence_count")
            if type(count) is not int or count <= 0: _error(f"{where}.exact_occurrence_count must be a positive integer")
            pairs[pair] = count
        else: _error(f"{where}.kind is invalid")
        edge_ids.append(identifier)
    if edge_ids != sorted(edge_ids): _error("payload.edges must have unique lexicographically sorted IDs")
    for identifier, node in nodes.items():
        if node["kind"] == "class":
            owner = owners.get(identifier)
            if owner != node["parent_id"]: _error(f"class {identifier!r} parent_id is inconsistent with contains edges")
            if owner in nodes and node["path"] != nodes[owner]["path"]: _error(f"class {identifier!r} path must match its root")

    statuses = {"exact": 0, "external": 0, "unresolved": 0}
    observed: dict[tuple[str, str], int] = {}
    reference_ids: list[str] = []
    reference_keys = {"id", "importer_id", "kind", "module", "name", "alias", "level", "location", "resolution", "target_id", "candidate_ids"}
    for index, value in enumerate(payload["import_references"]):
        where = f"payload.import_references[{index}]"; ref = _object(value, reference_keys, where)
        identifier = ref.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in reference_ids: _error(f"{where}.id is missing or duplicate")
        importer = ref.get("importer_id")
        if importer not in nodes or nodes[importer]["kind"] not in {"file", "module"}: _error(f"{where}.importer_id is invalid")
        kind, module, name, alias, level = ref.get("kind"), ref.get("module"), ref.get("name"), ref.get("alias"), ref.get("level")
        if kind not in {"import", "from"}: _error(f"{where}.kind is invalid")
        if not isinstance(module, str) or not isinstance(name, str) or not name: _error(f"{where} module or name is invalid")
        if alias is not None and (not isinstance(alias, str) or not alias): _error(f"{where}.alias is invalid")
        if type(level) is not int or level < 0: _error(f"{where}.level is invalid")
        if kind == "import" and (module or level != 0 or name == "*"): _error(f"{where} import spelling is invalid")
        if kind == "from" and level == 0 and not module: _error(f"{where} absolute from requires a module")
        location = _object(ref.get("location"), {"path", "line", "column"}, f"{where}.location")
        _relative_path(location.get("path"), f"{where}.location.path")
        if location["path"] != nodes[importer]["path"] or type(location.get("line")) is not int or location["line"] < 1 or type(location.get("column")) is not int or location["column"] < 0: _error(f"{where}.location is invalid")
        status = ref.get("resolution")
        if status not in statuses: _error(f"{where}.resolution is invalid")
        if status == "external" and level != 0: _error(f"{where} external resolution must be absolute")
        if status == "unresolved" and level == 0: _error(f"{where} unresolved resolution must be relative")
        if ref.get("candidate_ids") != []: _error(f"{where}.candidate_ids must be an empty array")
        target = ref.get("target_id")
        if status == "exact":
            if target not in nodes or nodes[target]["kind"] not in {"file", "module"}: _error(f"{where} exact resolution requires one root target")
            pair = (importer, target); observed[pair] = observed.get(pair, 0) + 1
        elif target is not None: _error(f"{where} non-exact resolution cannot have a target")
        statuses[status] += 1; reference_ids.append(identifier)
    if reference_ids != sorted(reference_ids): _error("payload.import_references must have unique lexicographically sorted IDs")
    counts = _object(payload["import_resolution_counts"], set(statuses), "payload.import_resolution_counts")
    if any(type(value) is not int or value < 0 for value in counts.values()): _error("import resolution counts must be nonnegative integers")
    if dict(counts) != statuses: _error("import resolution counts must match import references")
    if pairs != observed: _error("aggregate import pairs and counts must match exact import references")


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

    if profile["id"] == "dependency.files":
        _validate_dependency_files(root.get("payload"))
        fingerprint = root.get("view_fingerprint")
        if not isinstance(fingerprint, str) or not _HEX_64.fullmatch(fingerprint):
            _error("view_fingerprint must be lowercase SHA-256 hex")
        if verify_fingerprint and fingerprint != graph_view_fingerprint(root):
            _error("view_fingerprint does not match canonical content")
        return
    if profile["id"] == "dependency.architecture":
        _validate_dependency_architecture(root.get("payload"))
        fingerprint = root.get("view_fingerprint")
        if not isinstance(fingerprint, str) or not _HEX_64.fullmatch(fingerprint): _error("view_fingerprint must be lowercase SHA-256 hex")
        if verify_fingerprint and fingerprint != graph_view_fingerprint(root): _error("view_fingerprint does not match canonical content")
        return

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


__all__ = [
    "aggregate_import_edge_id", "graph_view_fingerprint", "serialize_graph_view",
    "validate_graph_view_v1",
]
