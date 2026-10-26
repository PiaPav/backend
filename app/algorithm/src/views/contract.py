"""Standalone validation, hashing and serialization for Graph View DTO v1."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import PurePosixPath
from typing import Any, Mapping

from graph_dto import CLASS_KINDS, CONTROL_KINDS, NODE_KINDS, OCCURRENCE_KINDS

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
_CALL_EDGE_KEYS = _EDGE_KEYS | {"weight"}
_CALL_STATUSES = ("exact", "ambiguous", "external", "dynamic", "unresolved")


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
        for name in ("nodes", "edges", "import_references", "callsites", "type_references"):
            values = payload.get(name)
            if isinstance(values, list):
                content["payload"][name] = sorted(
                    values,
                    key=lambda item: item.get("id", "") if isinstance(item, Mapping) else "",
                )
        facts = payload.get("owner_structural_facts")
        if isinstance(facts, list):
            content["payload"]["owner_structural_facts"] = sorted(
                facts, key=lambda item: item.get("owner_id", "") if isinstance(item, Mapping) else ""
            )
        owner_ids = payload.get("module_call_owner_ids")
        if isinstance(owner_ids, list):
            content["payload"]["module_call_owner_ids"] = sorted(owner_ids, key=lambda item: str(item))
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


def _validate_calls_topology(payload: Mapping[str, Any]) -> None:
    payload = _object(payload, {"nodes", "edges", "module_call_owner_ids", "callsite_counts"}, "payload")
    if not isinstance(payload["nodes"], list) or not isinstance(payload["edges"], list):
        _error("payload nodes and edges must be arrays")
    nodes: dict[str, Mapping[str, Any]] = {}
    node_ids: list[str] = []
    for index, value in enumerate(payload["nodes"]):
        where = f"payload.nodes[{index}]"
        if not isinstance(value, Mapping): _error(f"{where} must be an object")
        kind = value.get("kind")
        keys = {"id", "kind", "qualified_name", "path"}
        if kind not in {"file", "module"}: keys.add("parent_id")
        if kind == "method" and value.get("synthetic") is True: keys.add("synthetic")
        node = _object(value, keys, where)
        identifier = node.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in nodes:
            _error(f"{where}.id is missing or duplicate")
        if kind not in {"file", "module", "class", "function", "method"}:
            _error(f"{where}.kind is invalid")
        if not isinstance(node.get("qualified_name"), str): _error(f"{where}.qualified_name must be a string")
        _relative_path(node.get("path"), f"{where}.path")
        if kind not in {"file", "module"} and (not isinstance(node.get("parent_id"), str) or not node["parent_id"]):
            _error(f"{where}.parent_id is invalid")
        if "synthetic" in node and (kind != "method" or node["synthetic"] is not True):
            _error(f"{where}.synthetic is only allowed as true on methods")
        nodes[identifier] = node; node_ids.append(identifier)
    if node_ids != sorted(node_ids): _error("payload.nodes must have unique lexicographically sorted IDs")

    owners: dict[str, str] = {}
    triples: set[tuple[str, str, str]] = set()
    edge_ids: list[str] = []
    exact = {"awaited": 0, "non_awaited": 0}
    for index, value in enumerate(payload["edges"]):
        where = f"payload.edges[{index}]"
        if not isinstance(value, Mapping): _error(f"{where} must be an object")
        kind = value.get("kind")
        edge = _object(value, _EDGE_KEYS if kind == "contains" else _CALL_EDGE_KEYS, where)
        identifier = edge.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in edge_ids or identifier in nodes:
            _error(f"{where}.id is missing or duplicate")
        source, target = edge.get("source_id"), edge.get("target_id")
        if source not in nodes or target not in nodes: _error(f"{where} has a dangling endpoint")
        if kind == "contains":
            if target in owners: _error(f"node {target!r} has multiple containers")
            pair = (nodes[source]["kind"], nodes[target]["kind"])
            if pair not in {("file", "class"), ("module", "class"), ("file", "function"),
                            ("module", "function"), ("class", "method")}:
                _error(f"{where} has invalid ownership kinds")
            owners[target] = source
        elif kind in {"calls", "awaits"}:
            if nodes[source]["kind"] not in {"file", "module", "function", "method"} or nodes[target]["kind"] not in {"function", "method"}:
                _error(f"{where} has invalid call endpoint kinds")
            triple = (source, target, kind)
            if triple in triples: _error(f"{where} duplicates a call triple")
            triples.add(triple)
            weight = edge.get("weight")
            if type(weight) is not int or weight <= 0: _error(f"{where}.weight must be a positive integer")
            exact["awaited" if kind == "awaits" else "non_awaited"] += weight
        else: _error(f"{where}.kind is invalid")
        edge_ids.append(identifier)
    if edge_ids != sorted(edge_ids): _error("payload.edges must have unique lexicographically sorted IDs")

    for identifier, node in nodes.items():
        kind = node["kind"]
        if kind in {"file", "module"}:
            if identifier in owners: _error(f"root {identifier!r} must not have an owner")
        elif owners.get(identifier) != node["parent_id"]:
            _error(f"node {identifier!r} parent_id is inconsistent with contains edges")
        if kind == "class" and not any(owner == identifier and nodes[child]["kind"] == "method" for child, owner in owners.items()):
            _error(f"class {identifier!r} must own at least one method")
        current, seen = identifier, set()
        while current in owners:
            if current in seen: _error("contains edges must form an acyclic forest")
            seen.add(current); current = owners[current]
        if nodes[current]["kind"] not in {"file", "module"}: _error(f"node {identifier!r} has no owning root")
        if node["path"] != nodes[current]["path"]: _error(f"node {identifier!r} path must match its root")

    owner_ids = payload["module_call_owner_ids"]
    if not isinstance(owner_ids, list) or owner_ids != sorted(owner_ids) or len(owner_ids) != len(set(owner_ids)):
        _error("module_call_owner_ids must be unique and lexicographically sorted")
    if any(identifier not in nodes or nodes[identifier]["kind"] not in {"file", "module"} for identifier in owner_ids):
        _error("module_call_owner_ids must reference root nodes")
    ownership_roots = {
        owner for child, owner in owners.items()
        if nodes[owner]["kind"] in {"file", "module"}
        and nodes[child]["kind"] in {"class", "function"}
    }
    if any(node["kind"] in {"file", "module"} and identifier not in owner_ids
           and identifier not in ownership_roots for identifier, node in nodes.items()):
        _error("every root must own a callable or be a module call owner")
    for source, _target, kind in triples:
        if nodes[source]["kind"] in {"file", "module"} and source not in owner_ids:
            _error(f"{kind} root source must be a module call owner")

    counts = _object(payload["callsite_counts"], set(_CALL_STATUSES), "payload.callsite_counts")
    for status in _CALL_STATUSES:
        row = _object(counts[status], {"awaited", "non_awaited"}, f"payload.callsite_counts.{status}")
        if any(type(value) is not int or value < 0 for value in row.values()):
            _error("callsite counts must be nonnegative integers")
    if dict(counts["exact"]) != exact: _error("exact callsite counts must equal call edge weights")
    exact_root_sources = {
        source for source, _target, _kind in triples
        if nodes[source]["kind"] in {"file", "module"}
    }
    owners_requiring_non_exact = set(owner_ids) - exact_root_sources
    non_exact_total = sum(
        value
        for status, row in counts.items()
        if status != "exact"
        for value in row.values()
    )
    if non_exact_total < len(owners_requiring_non_exact):
        _error("non-exact callsite counts must cover module call owners without an exact root edge")


def _validate_types_topology(payload: Mapping[str, Any]) -> None:
    payload = _object(payload, {"nodes", "edges", "type_references"}, "payload")
    if not all(isinstance(payload[name], list) for name in payload):
        _error("types.topology payload fields must be arrays")
    nodes: dict[str, Mapping[str, Any]] = {}; node_ids: list[str] = []
    for index, value in enumerate(payload["nodes"]):
        where = f"payload.nodes[{index}]"
        if not isinstance(value, Mapping): _error(f"{where} must be an object")
        kind = value.get("kind"); keys = _DEPENDENCY_NODE_KEYS if kind in {"file", "module"} else _NODE_REQUIRED
        node = _object(value, keys, where); identifier = node.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in nodes: _error(f"{where}.id is missing or duplicate")
        if kind not in {"file", "module", "class", "field"}: _error(f"{where}.kind is invalid")
        if not isinstance(node.get("qualified_name"), str): _error(f"{where}.qualified_name must be a string")
        _relative_path(node.get("path"), f"{where}.path")
        if kind not in {"file", "module"} and (not isinstance(node.get("parent_id"), str) or not node["parent_id"]): _error(f"{where}.parent_id is invalid")
        nodes[identifier] = node; node_ids.append(identifier)
    if node_ids != sorted(node_ids): _error("payload.nodes must have unique lexicographically sorted IDs")

    owners: dict[str, str] = {}; topology: set[tuple[str, str, str]] = set(); edge_ids: list[str] = []
    for index, value in enumerate(payload["edges"]):
        where = f"payload.edges[{index}]"; edge = _object(value, _EDGE_KEYS, where); identifier = edge.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in edge_ids or identifier in nodes: _error(f"{where}.id is missing or duplicate")
        source, target, kind = edge.get("source_id"), edge.get("target_id"), edge.get("kind")
        if source not in nodes or target not in nodes: _error(f"{where} has a dangling endpoint")
        if kind == "contains":
            if target in owners: _error(f"node {target!r} has multiple containers")
            if (nodes[source]["kind"], nodes[target]["kind"]) not in {("file", "class"), ("module", "class"), ("class", "field")}: _error(f"{where} has invalid ownership kinds")
            owners[target] = source
        elif kind in {"inherits", "field_type"}:
            expected = ("class", "class") if kind == "inherits" else ("field", "class")
            if (nodes[source]["kind"], nodes[target]["kind"]) != expected: _error(f"{where} has invalid type relation endpoint kinds")
            topology.add((kind, source, target))
        else: _error(f"{where}.kind is invalid")
        edge_ids.append(identifier)
    if edge_ids != sorted(edge_ids): _error("payload.edges must have unique lexicographically sorted IDs")

    roots_with_classes: set[str] = set()
    for identifier, node in nodes.items():
        if node["kind"] in {"file", "module"}:
            if identifier in owners: _error(f"root {identifier!r} must not have an owner")
        elif owners.get(identifier) != node["parent_id"]: _error(f"node {identifier!r} parent_id is inconsistent with contains edges")
        current, seen = identifier, set()
        while current in owners:
            if current in seen: _error("contains edges must form an acyclic forest")
            seen.add(current); current = owners[current]
        if nodes[current]["kind"] not in {"file", "module"}: _error(f"node {identifier!r} has no owning root")
        if node["path"] != nodes[current]["path"]: _error(f"node {identifier!r} path must match its root")
        if node["kind"] == "class": roots_with_classes.add(current)
    roots = {identifier for identifier, node in nodes.items() if node["kind"] in {"file", "module"}}
    if roots != roots_with_classes: _error("every included root must own a class")

    references: set[tuple[str, str, str]] = set(); reference_ids: list[str] = []
    reference_keys = {"id", "owner_id", "role", "expression", "location", "resolution", "target_id", "candidate_ids"}
    for index, value in enumerate(payload["type_references"]):
        where = f"payload.type_references[{index}]"; reference = _object(value, reference_keys, where); identifier = reference.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in reference_ids: _error(f"{where}.id is missing or duplicate")
        owner, role = reference.get("owner_id"), reference.get("role"); expected_owner = "class" if role == "base" else "field" if role == "field_type" else None
        if owner not in nodes or nodes[owner]["kind"] != expected_owner: _error(f"{where}.owner_id or role is invalid")
        if not isinstance(reference.get("expression"), str) or not reference["expression"]: _error(f"{where}.expression is required")
        _view_location(reference.get("location"), f"{where}.location")
        candidates = reference.get("candidate_ids")
        if not isinstance(candidates, list) or any(not isinstance(item, str) for item in candidates) or candidates != sorted(candidates) or len(candidates) != len(set(candidates)): _error(f"{where}.candidate_ids must be unique and sorted")
        if any(item not in nodes or nodes[item]["kind"] != "class" for item in candidates): _error(f"{where}.candidate_ids must reference classes")
        status, target = reference.get("resolution"), reference.get("target_id")
        if status == "exact":
            if target not in nodes or nodes[target]["kind"] != "class" or candidates: _error(f"{where} exact resolution requires one class target")
            references.add(("inherits" if role == "base" else "field_type", owner, target))
        elif status == "ambiguous":
            if target is not None or len(candidates) < 2: _error(f"{where} ambiguous resolution requires >=2 candidates")
        elif status in {"external", "unresolved"}:
            if target is not None or candidates: _error(f"{where} non-exact resolution cannot have targets")
        else: _error(f"{where}.resolution is invalid")
        reference_ids.append(identifier)
    if reference_ids != sorted(reference_ids): _error("payload.type_references must have unique lexicographically sorted IDs")
    if topology != references: _error("type topology must exactly match exact type references")


def _view_location(value: Any, where: str, path: str | None = None) -> tuple[int, int]:
    location = _object(value, {"path", "line", "column"}, where)
    _relative_path(location.get("path"), f"{where}.path")
    if path is not None and location["path"] != path:
        _error(f"{where}.path must match its owner path")
    if type(location.get("line")) is not int or location["line"] < 1:
        _error(f"{where}.line is invalid")
    if type(location.get("column")) is not int or location["column"] < 0:
        _error(f"{where}.column is invalid")
    return location["line"], location["column"]


def _validate_view_complexity(value: Any, where: str, path: str) -> None:
    facts = _object(value, {"span", "is_async", "controls", "occurrences"}, where)
    if type(facts.get("is_async")) is not bool:
        _error(f"{where}.is_async must be a boolean")
    span = _object(facts.get("span"), {"start", "end"}, f"{where}.span")
    start = _view_location(span.get("start"), f"{where}.span.start", path)
    end = _view_location(span.get("end"), f"{where}.span.end", path)
    if end < start: _error(f"{where}.span is reversed")
    controls, occurrences = facts.get("controls"), facts.get("occurrences")
    if not isinstance(controls, list) or not isinstance(occurrences, list):
        _error(f"{where} controls and occurrences must be arrays")
    depths: list[int] = []
    required = {"kind", "parent_index", "location", "operand_count", "case_count", "filter_count"}
    for index, value in enumerate(controls):
        item_where = f"{where}.controls[{index}]"
        if not isinstance(value, Mapping) or not required <= set(value) or not set(value) <= required | {"expression"}:
            _error(f"{item_where} has invalid fields")
        kind, parent = value.get("kind"), value.get("parent_index")
        if kind not in CONTROL_KINDS: _error(f"{item_where}.kind is invalid")
        if parent is not None and (type(parent) is not int or parent < 0 or parent >= index):
            _error(f"{item_where}.parent_index must reference an earlier control")
        depths.append(0 if parent is None else depths[parent] + 1)
        position = _view_location(value.get("location"), f"{item_where}.location", path)
        if not start <= position <= end: _error(f"{item_where}.location is outside the callable span")
        for field, used, minimum in (("operand_count", kind == "boolean", 2),
                                     ("case_count", kind == "match", 1),
                                     ("filter_count", kind == "comprehension", 0)):
            count = value.get(field)
            if type(count) is not int or (used and count < minimum) or (not used and count != 0):
                _error(f"{item_where}.{field} is invalid")
        if kind == "exception_handler":
            if not isinstance(value.get("expression"), str) or not value["expression"]:
                _error(f"{item_where}.expression is required")
        elif "expression" in value: _error(f"{item_where}.expression is not allowed")
    for index, value in enumerate(occurrences):
        item_where = f"{where}.occurrences[{index}]"
        if not isinstance(value, Mapping) or not {"kind", "location"} <= set(value) or not set(value) <= {"kind", "location", "expression"}:
            _error(f"{item_where} has invalid fields")
        kind = value.get("kind")
        if kind not in OCCURRENCE_KINDS: _error(f"{item_where}.kind is invalid")
        position = _view_location(value.get("location"), f"{item_where}.location", path)
        if not start <= position <= end: _error(f"{item_where}.location is outside the callable span")
        expression = value.get("expression")
        if kind == "self_attribute" and (not isinstance(expression, str) or not expression):
            _error(f"{item_where}.expression is required")
        if "expression" in value and kind not in {"raise", "self_attribute"}:
            _error(f"{item_where}.expression is not allowed")
        if kind == "raise" and "expression" in value and (not isinstance(expression, str) or not expression):
            _error(f"{item_where}.expression is invalid")


def _validate_calls_detailed(payload: Mapping[str, Any]) -> None:
    payload = _object(payload, {"nodes", "edges", "callsites", "module_call_owner_ids", "owner_structural_facts"}, "payload")
    if not all(isinstance(payload[name], list) for name in payload):
        _error("calls.detailed payload fields must be arrays")
    nodes: dict[str, Mapping[str, Any]] = {}; node_ids: list[str] = []
    for index, value in enumerate(payload["nodes"]):
        where = f"payload.nodes[{index}]"
        if not isinstance(value, Mapping): _error(f"{where} must be an object")
        kind = value.get("kind"); keys = {"id", "kind", "qualified_name", "path"}
        if kind not in {"file", "module"}: keys.add("parent_id")
        if kind in {"function", "method"}:
            keys.add("synthetic" if value.get("synthetic") is True else "complexity_facts")
        node = _object(value, keys, where); identifier = node.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in nodes: _error(f"{where}.id is missing or duplicate")
        if kind not in {"file", "module", "class", "function", "method"}: _error(f"{where}.kind is invalid")
        if not isinstance(node.get("qualified_name"), str): _error(f"{where}.qualified_name must be a string")
        _relative_path(node.get("path"), f"{where}.path")
        if kind not in {"file", "module"} and (not isinstance(node.get("parent_id"), str) or not node["parent_id"]): _error(f"{where}.parent_id is invalid")
        if "synthetic" in node and (kind != "method" or node["synthetic"] is not True): _error(f"{where}.synthetic is invalid")
        if "complexity_facts" in node: _validate_view_complexity(node["complexity_facts"], f"{where}.complexity_facts", node["path"])
        nodes[identifier] = node; node_ids.append(identifier)
    if node_ids != sorted(node_ids): _error("payload.nodes must have unique lexicographically sorted IDs")

    owners: dict[str, str] = {}; triples: dict[tuple[str, str, str], int] = {}; edge_ids: list[str] = []
    for index, value in enumerate(payload["edges"]):
        where = f"payload.edges[{index}]"; kind = value.get("kind") if isinstance(value, Mapping) else None
        edge = _object(value, _EDGE_KEYS if kind == "contains" else _CALL_EDGE_KEYS, where)
        identifier = edge.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in edge_ids or identifier in nodes: _error(f"{where}.id is missing or duplicate")
        source, target = edge.get("source_id"), edge.get("target_id")
        if source not in nodes or target not in nodes: _error(f"{where} has a dangling endpoint")
        if kind == "contains":
            pair = (nodes[source]["kind"], nodes[target]["kind"])
            if pair not in {("file", "class"), ("module", "class"), ("file", "function"), ("module", "function"), ("class", "method")}:
                _error(f"{where} has invalid ownership kinds")
            if target in owners: _error(f"node {target!r} has multiple containers")
            owners[target] = source
        elif kind in {"calls", "awaits"}:
            if nodes[source]["kind"] not in {"file", "module", "function", "method"} or nodes[target]["kind"] not in {"function", "method"}: _error(f"{where} has invalid call endpoint kinds")
            triple = (source, target, kind); weight = edge.get("weight")
            if triple in triples: _error(f"{where} duplicates a call triple")
            if type(weight) is not int or weight <= 0: _error(f"{where}.weight must be a positive integer")
            triples[triple] = weight
        else: _error(f"{where}.kind is invalid")
        edge_ids.append(identifier)
    if edge_ids != sorted(edge_ids): _error("payload.edges must have unique lexicographically sorted IDs")
    for identifier, node in nodes.items():
        if node["kind"] in {"file", "module"}:
            if identifier in owners: _error(f"root {identifier!r} must not have an owner")
        elif owners.get(identifier) != node["parent_id"]: _error(f"node {identifier!r} parent_id is inconsistent with contains edges")
        if node["kind"] == "class" and not any(owner == identifier and nodes[child]["kind"] == "method" for child, owner in owners.items()): _error(f"class {identifier!r} must own at least one method")
        current, seen = identifier, set()
        while current in owners:
            if current in seen: _error("contains edges must form an acyclic forest")
            seen.add(current); current = owners[current]
        if nodes[current]["kind"] not in {"file", "module"}: _error(f"node {identifier!r} has no owning root")
        if node["path"] != nodes[current]["path"]: _error(f"node {identifier!r} path must match its root")

    observed: dict[tuple[str, str, str], int] = {}; root_callers: set[str] = set(); callsite_ids: list[str] = []
    callsite_keys = {"id", "caller_id", "expression", "location", "syntactic_depth", "resolution", "target_id", "candidate_ids", "awaited"}
    for index, value in enumerate(payload["callsites"]):
        where = f"payload.callsites[{index}]"; callsite = _object(value, callsite_keys, where); identifier = callsite.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in callsite_ids: _error(f"{where}.id is missing or duplicate")
        caller = callsite.get("caller_id")
        if caller not in nodes or nodes[caller]["kind"] not in {"file", "module", "function", "method"}: _error(f"{where}.caller_id is invalid")
        if nodes[caller]["kind"] in {"file", "module"}: root_callers.add(caller)
        if not isinstance(callsite.get("expression"), str) or not callsite["expression"]: _error(f"{where}.expression is required")
        _view_location(callsite.get("location"), f"{where}.location")
        if type(callsite.get("syntactic_depth")) is not int or callsite["syntactic_depth"] < 0: _error(f"{where}.syntactic_depth is invalid")
        if type(callsite.get("awaited")) is not bool: _error(f"{where}.awaited must be a boolean")
        status, target, candidates = callsite.get("resolution"), callsite.get("target_id"), callsite.get("candidate_ids")
        if status not in _CALL_STATUSES: _error(f"{where}.resolution is invalid")
        if (not isinstance(candidates, list) or any(not isinstance(item, str) for item in candidates)
                or candidates != sorted(candidates) or len(candidates) != len(set(candidates))):
            _error(f"{where}.candidate_ids must be unique and sorted")
        if any(item not in nodes or nodes[item]["kind"] not in {"function", "method"} for item in candidates): _error(f"{where}.candidate_ids are invalid")
        if status == "exact":
            if target not in nodes or nodes[target]["kind"] not in {"function", "method"} or candidates: _error(f"{where} exact resolution requires exactly target_id")
            triple = (caller, target, "awaits" if callsite["awaited"] else "calls"); observed[triple] = observed.get(triple, 0) + 1
        elif status == "ambiguous":
            if target is not None or len(candidates) < 2: _error(f"{where} ambiguous resolution requires >=2 candidates")
        elif target is not None or candidates: _error(f"{where} non-internal resolution cannot have targets")
        callsite_ids.append(identifier)
    if callsite_ids != sorted(callsite_ids): _error("payload.callsites must have unique lexicographically sorted IDs")
    if observed != triples: _error("call edge triples and weights must exactly match exact callsites")
    owner_ids = payload["module_call_owner_ids"]
    if any(not isinstance(item, str) for item in owner_ids) or owner_ids != sorted(owner_ids) or len(owner_ids) != len(set(owner_ids)) or set(owner_ids) != root_callers: _error("module_call_owner_ids must exactly equal sorted root callsite callers")

    expected_facts = {identifier for identifier, node in nodes.items() if node["kind"] in {"file", "module"} or (node["kind"] in {"function", "method"} and node.get("synthetic") is not True)}
    fact_ids: list[str] = []
    for index, value in enumerate(payload["owner_structural_facts"]):
        fact = _object(value, {"owner_id", "call_occurrences"}, f"payload.owner_structural_facts[{index}]"); owner = fact.get("owner_id")
        if owner not in expected_facts or owner in fact_ids: _error(f"payload.owner_structural_facts[{index}].owner_id is invalid or duplicate")
        if type(fact.get("call_occurrences")) is not int or fact["call_occurrences"] < 0: _error(f"payload.owner_structural_facts[{index}].call_occurrences is invalid")
        fact_ids.append(owner)
    if fact_ids != sorted(expected_facts): _error("owner_structural_facts must exactly contain every structural owner in sorted order")


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
    if profile["id"] == "calls.topology":
        _validate_calls_topology(root.get("payload"))
        fingerprint = root.get("view_fingerprint")
        if not isinstance(fingerprint, str) or not _HEX_64.fullmatch(fingerprint): _error("view_fingerprint must be lowercase SHA-256 hex")
        if verify_fingerprint and fingerprint != graph_view_fingerprint(root): _error("view_fingerprint does not match canonical content")
        return
    if profile["id"] == "calls.detailed":
        _validate_calls_detailed(root.get("payload"))
        fingerprint = root.get("view_fingerprint")
        if not isinstance(fingerprint, str) or not _HEX_64.fullmatch(fingerprint): _error("view_fingerprint must be lowercase SHA-256 hex")
        if verify_fingerprint and fingerprint != graph_view_fingerprint(root): _error("view_fingerprint does not match canonical content")
        return
    if profile["id"] == "types.topology":
        _validate_types_topology(root.get("payload"))
        fingerprint = root.get("view_fingerprint")
        if not isinstance(fingerprint, str) or not _HEX_64.fullmatch(fingerprint):
            _error("view_fingerprint must be lowercase SHA-256 hex")
        if verify_fingerprint and fingerprint != graph_view_fingerprint(root):
            _error("view_fingerprint does not match canonical content")
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
