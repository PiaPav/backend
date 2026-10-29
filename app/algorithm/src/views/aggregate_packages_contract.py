"""Normative compact wire and decoder for aggregate.packages v2."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


def _aggregate_package_grouping_v1() -> dict[str, Any]:
    """Build the normative descriptor without sharing mutable state."""
    return {
        "descriptor_version": 1,
        "path_policy": {
            "separator": "/", "package": "first POSIX path segment", "root_package": "<root>",
            "root_condition": "path contains no '/'",
        },
        "populations": {
            "files": "all canonical file/module roots",
            "declarations": "all canonical non-root nodes attributed through their owning root; synthetic methods included",
            "classes": "canonical classes directly owned by roots",
            "abstract_classes": "direct-root-owned classes with class_kind abstract",
            "import_occurrences": "all canonical import references attributed by importer root package",
        },
        "quotient_edges": {
            "direction": "dependent package to dependency package",
            "source_relation": "exact canonical root imports", "self_edges": "omitted",
            "non_exact_relations": "do not create edges",
        },
    }


def aggregate_package_grouping_v1() -> dict[str, Any]:
    """Return a fresh aggregate.packages v2 grouping descriptor."""
    return _aggregate_package_grouping_v1()


def _digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def aggregate_package_id(label: str) -> str:
    return "aggregate:package:" + _digest(
        ["aggregate.packages", 2, _aggregate_package_grouping_v1(), label]
    )


def aggregate_package_edge_id(source_id: str, target_id: str) -> str:
    return "aggregate:package-imports:" + _digest(
        ["aggregate.packages", 2, source_id, target_id]
    )


def _fail(message: str) -> None:
    raise ValueError(f"Invalid aggregate.packages v2 wire: {message}")


def _count(value: Any, where: str, *, positive: bool = False) -> int:
    if type(value) is not int or value < (1 if positive else 0):
        _fail(f"{where} must be a {'positive' if positive else 'non-negative'} integer")
    return value


def decode_aggregate_packages_v2(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Strictly validate and expand a compact payload without mutating it."""
    if not isinstance(payload, Mapping) or set(payload) != {
        "graph_kind", "wire_format", "grouping_version", "packages", "imports"
    }:
        _fail("payload must be an object with exact fields")
    if (payload["graph_kind"] != "quotient"
            or type(payload["wire_format"]) is not int or payload["wire_format"] != 2
            or type(payload["grouping_version"]) is not int or payload["grouping_version"] != 1):
        _fail("unknown graph, wire, or grouping version")
    rows, imports = payload["packages"], payload["imports"]
    if not isinstance(rows, list) or not isinstance(imports, list):
        _fail("packages and imports must be arrays")
    nodes, ids, labels = [], [], set()
    for index, row in enumerate(rows):
        where = f"packages[{index}]"
        if not isinstance(row, list) or len(row) != 10:
            _fail(f"{where} must have exactly 10 positional fields")
        label = row[0]
        if not isinstance(label, str) or not label or label in labels:
            _fail(f"{where} label must be a unique non-empty string")
        counts = [_count(value, f"{where}[{offset}]", positive=offset == 1)
                  for offset, value in enumerate(row[1:], 1)]
        files, declarations, classes, abstract, external, unresolved, unique, exact, self_count = counts
        if abstract > classes or classes > declarations or unique > exact or self_count > exact:
            _fail(f"{where} count invariant is violated")
        identifier = aggregate_package_id(label)
        ids.append(identifier); labels.add(label)
        nodes.append({
            "id": identifier, "package": label, "file_count": files,
            "declaration_count": declarations, "class_count": classes,
            "abstract_class_count": abstract,
            "import_occurrence_counts": {"exact": exact, "external": external, "unresolved": unresolved},
            "internal_imports": {"unique_file_pair_count": unique,
                                 "canonical_import_edge_count": exact,
                                 "exact_import_occurrence_count": exact,
                                 "self_import_occurrence_count": self_count},
        })
    if ids != sorted(ids):
        _fail("package rows are not in canonical package ID order")
    edges, edge_ids, pairs = [], [], set()
    for index, row in enumerate(imports):
        where = f"imports[{index}]"
        if not isinstance(row, list) or len(row) != 4:
            _fail(f"{where} must have exactly 4 positional fields")
        source, target = row[0], row[1]
        if type(source) is not int or type(target) is not int or not (0 <= source < len(ids)) or not (0 <= target < len(ids)):
            _fail(f"{where} has invalid endpoint indexes")
        if source == target or (source, target) in pairs:
            _fail(f"{where} is a package self-edge or duplicate ordered pair")
        unique = _count(row[2], f"{where}[2]", positive=True)
        exact = _count(row[3], f"{where}[3]", positive=True)
        if unique > exact:
            _fail(f"{where} unique count exceeds exact count")
        identifier = aggregate_package_edge_id(ids[source], ids[target])
        edge_ids.append(identifier); pairs.add((source, target))
        edges.append({"id": identifier, "kind": "imports", "source_id": ids[source],
                      "target_id": ids[target], "unique_file_pair_count": unique,
                      "canonical_import_edge_count": exact,
                      "exact_import_occurrence_count": exact})
        nodes[source]["import_occurrence_counts"]["exact"] += exact
    if edge_ids != sorted(edge_ids):
        _fail("import rows are not in canonical edge ID order")
    return {"graph_kind": "quotient", "package_grouping": _aggregate_package_grouping_v1(),
            "nodes": nodes, "edges": edges}


__all__ = ["aggregate_package_edge_id", "aggregate_package_grouping_v1",
           "aggregate_package_id", "decode_aggregate_packages_v2"]
