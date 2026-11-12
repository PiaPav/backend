"""Normative compact wire contract for ``aggregate.overview/1``."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


def _grouping() -> dict[str, Any]:
    return {"descriptor_version": 1, "path_policy": {
        "separator": "/", "package": "first POSIX path segment",
        "root_package": "<root>", "root_condition": "path contains no '/'"},
        "populations": {"files": "all canonical file/module roots",
                        "edges": "unique exact non-self root pairs",
                        "packages": "labels represented by roots"}}


def _populations() -> dict[str, Any]:
    return {"descriptor_version": 1,
            "size": "canonical graph nodes and non-empty root path prefixes",
            "activity": "owner structural occurrence facts",
            "topology": "unique exact non-self file pairs and package quotient pairs",
            "resolution_counts": "canonical reference occurrences, zero-filled"}


def _top_k() -> dict[str, Any]:
    return {"descriptor_version": 1, "limit": 10, "ties": "do not expand boundary",
            "order": "score descending then authoritative ID ascending",
            "empty_metadata": [0, 0, False]}


def _compact(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def aggregate_overview_package_id(label: str) -> str:
    return "aggregate:overview-package:" + hashlib.sha256(
        _compact(["aggregate.overview", 1, _grouping(), label])).hexdigest()


def _fail(message: str) -> None:
    raise ValueError(f"Invalid aggregate.overview v1 wire: {message}")


def _counts(value: Any, length: int, where: str) -> list[int]:
    if not isinstance(value, list) or len(value) != length:
        _fail(f"{where} must contain exactly {length} values")
    if any(type(item) is not int or item < 0 for item in value):
        _fail(f"{where} values must be non-negative integers")
    return list(value)


def _identities(value: Any, package: bool) -> tuple[list[list[str]], list[str]]:
    where = "package_identities" if package else "file_identities"
    if not isinstance(value, list):
        _fail(f"{where} must be an array")
    rows: list[list[str]] = []
    for index, row in enumerate(value):
        if (not isinstance(row, list) or len(row) != 2
                or any(not isinstance(item, str) or not item for item in row)):
            _fail(f"{where}[{index}] must be a pair of non-empty strings")
        if package and row[0] != aggregate_overview_package_id(row[1]):
            _fail(f"{where}[{index}] has a non-canonical package ID")
        rows.append(list(row))
    ids = [row[0] for row in rows]
    if ids != sorted(set(ids)):
        _fail(f"{where} must be in unique canonical ID order")
    if len({row[1] for row in rows}) != len(rows):
        _fail(f"{where} descriptors must be unique")
    return rows, ids


def decode_aggregate_overview_v1(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Strictly validate positional wire data and return a fresh logical tree."""
    keys = {"graph_kind", "wire_format", "policy_version", "totals", "statuses",
            "file_identities", "package_identities", "rankings"}
    if not isinstance(payload, Mapping) or set(payload) != keys:
        _fail("payload must be an object with exact fields")
    if (payload["graph_kind"] != "overview" or type(payload["wire_format"]) is not int
            or payload["wire_format"] != 1 or type(payload["policy_version"]) is not int
            or payload["policy_version"] != 1):
        _fail("unknown graph, wire, or policy version")
    totals = _counts(payload["totals"], 19, "totals")
    statuses = _counts(payload["statuses"], 12, "statuses")
    file_rows, file_ids = _identities(payload["file_identities"], False)
    package_rows, package_ids = _identities(payload["package_identities"], True)
    rankings = payload["rankings"]
    if not isinstance(rankings, list) or len(rankings) != 3:
        _fail("rankings must contain exactly three rows")
    decoded_rankings = []
    used = [set(), set()]
    for ordinal, row in enumerate(rankings):
        where = f"rankings[{ordinal}]"
        if not isinstance(row, list) or len(row) != 4:
            _fail(f"{where} must have exactly four fields")
        total, returned = (_counts([row[0], row[1]], 2, where)[:2])
        truncated, items = row[2], row[3]
        if type(truncated) is not bool or not isinstance(items, list) or returned != len(items):
            _fail(f"{where} metadata is inconsistent")
        if returned > 10 or returned > total or truncated != (returned < total):
            _fail(f"{where} truncation metadata is inconsistent")
        table, ids, table_kind = ((package_rows, package_ids, 1) if ordinal == 2
                                  else (file_rows, file_ids, 0))
        logical, seen, order = [], set(), []
        for item_index, item in enumerate(items):
            if (not isinstance(item, list) or len(item) != 2 or type(item[0]) is not int
                    or not 0 <= item[0] < len(table)):
                _fail(f"{where}.items[{item_index}] has an invalid identity index")
            score = item[1]
            if type(score) is not int or score <= 0 or item[0] in seen:
                _fail(f"{where}.items[{item_index}] has invalid or duplicate data")
            seen.add(item[0]); used[table_kind].add(item[0])
            identifier, label = table[item[0]]
            order.append((-score, identifier))
            logical.append({"id": identifier, "label" if ordinal == 2 else "path": label,
                            "score": score})
        if order != sorted(order):
            _fail(f"{where} is not in canonical ranking order")
        decoded_rankings.append({"items": logical, "returned_count": returned,
                                 "total_matching": total, "truncated": truncated})
    if used[0] != set(range(len(file_rows))) or used[1] != set(range(len(package_rows))):
        _fail("identity tables must equal the union of referenced ranking items")
    size_names = ("directories", "files", "classes", "abstract_classes", "dataclasses",
                  "functions", "methods", "synthetic_methods", "fields", "constants")
    status_groups = (("exact", "external", "unresolved"),
                     ("exact", "ambiguous", "external", "unresolved"),
                     ("exact", "ambiguous", "external", "dynamic", "unresolved"))
    offset = 0; resolution = {}
    for domain, names in zip(("imports", "types", "callsites"), status_groups):
        resolution[domain] = dict(zip(names, statuses[offset:offset + len(names)])); offset += len(names)
    return {"size": dict(zip(size_names, totals[:10])),
            "activity": {"calls": totals[10], "local_imports": totals[11],
                         "external_imports": totals[12]},
            "file_graph": dict(zip(("vertices", "edges", "cyclic_components"), totals[13:16])),
            "package_graph": dict(zip(("vertices", "edges", "cyclic_components"), totals[16:19])),
            "resolution_counts": resolution,
            "hotspots": dict(zip(("files_by_fan_in", "files_by_fan_out",
                                   "packages_by_efferent_coupling"), decoded_rankings)),
            "populations": _populations(), "top_k": _top_k(), "package_grouping": _grouping()}


__all__ = ["aggregate_overview_package_id", "decode_aggregate_overview_v1"]
