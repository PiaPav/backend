"""Deterministic canonical Graph DTO family for package quotient benchmarks."""
from __future__ import annotations

from typing import Any

from graph_dto import graph_fingerprint, validate_graph_v1

_PACKAGE_COUNTS = {"medium": 4, "large": 10}


def _location(path: str, line: int, column: int = 0) -> dict[str, Any]:
    return {"path": path, "line": line, "column": column}


def build_representative_packages_v1(size: str) -> dict[str, Any]:
    """Build a fixed package-rich schema-1/semantics-7 source fixture."""
    if size not in _PACKAGE_COUNTS:
        raise ValueError(f"Unsupported representative packages size {size!r}")

    package_labels = ["<root>"] + [
        f"pkg{ordinal:02d}" for ordinal in range(1, _PACKAGE_COUNTS[size] + 1)
    ]
    graph: dict[str, Any] = {
        "schema_version": 1,
        "parser_semantics_version": 7,
        "project": {"fingerprint": ""},
        "nodes": [],
        "edges": [],
        "callsites": [],
        "type_references": [],
        "import_references": [],
        "owner_structural_facts": [],
        "diagnostics": [],
    }
    files: dict[str, dict[str, str]] = {}

    for package_index, package in enumerate(package_labels):
        prefix = "" if package == "<root>" else f"{package}/"
        paths = {role: f"{prefix}{role}.py" for role in ("source_a", "source_b", "sink")}
        ids = {role: f"file:{path}" for role, path in paths.items()}
        files[package] = ids
        for role, path in paths.items():
            module = path[:-3].replace("/", ".")
            graph["nodes"].append({
                "id": ids[role], "kind": "file", "qualified_name": module,
                "parent_id": None, "path": path, "location": _location(path, 1),
            })
            graph["owner_structural_facts"].append({
                "owner_id": ids[role], "call_occurrences": 0,
                "direct_import_occurrences": {"project_local": 0, "non_project": 0},
            })

        abstract_id = f"class:{paths['source_a']}:10:0:AbstractPort{package_index}"
        field_id = f"field:{paths['source_a']}:12:4:AbstractPort{package_index}.value"
        synthetic_id = f"method:{paths['source_a']}:10:0:AbstractPort{package_index}.__init__"
        concrete_id = f"class:{paths['source_b']}:10:0:Worker{package_index}"
        constant_id = f"constant:{paths['sink']}:5:0:LIMIT:{package_index + 1}"
        declarations = [
            {"id": abstract_id, "kind": "class", "class_kind": "abstract",
             "qualified_name": f"{paths['source_a'][:-3].replace('/', '.')}.AbstractPort{package_index}",
             "parent_id": ids["source_a"], "path": paths["source_a"],
             "location": _location(paths["source_a"], 10)},
            {"id": field_id, "kind": "field",
             "qualified_name": f"{paths['source_a'][:-3].replace('/', '.')}.AbstractPort{package_index}.value",
             "parent_id": abstract_id, "path": paths["source_a"],
             "location": _location(paths["source_a"], 12, 4)},
            {"id": synthetic_id, "kind": "method", "synthetic": True,
             "qualified_name": f"{paths['source_a'][:-3].replace('/', '.')}.AbstractPort{package_index}.__init__",
             "parent_id": abstract_id, "path": paths["source_a"],
             "location": _location(paths["source_a"], 10)},
            {"id": concrete_id, "kind": "class", "class_kind": "class",
             "qualified_name": f"{paths['source_b'][:-3].replace('/', '.')}.Worker{package_index}",
             "parent_id": ids["source_b"], "path": paths["source_b"],
             "location": _location(paths["source_b"], 10)},
            {"id": constant_id, "kind": "constant",
             "qualified_name": f"{paths['sink'][:-3].replace('/', '.')}.LIMIT",
             "parent_id": ids["sink"], "path": paths["sink"],
             "location": _location(paths["sink"], 5)},
        ]
        graph["nodes"].extend(declarations)
        for declaration in declarations:
            graph["edges"].append({
                "id": f"contains:{declaration['parent_id']}->{declaration['id']}",
                "kind": "contains", "source_id": declaration["parent_id"],
                "target_id": declaration["id"],
            })

    reference_ordinal = 0

    def add_import(package: str, source_role: str, target_id: str | None,
                   resolution: str, module: str, name: str, line: int) -> None:
        nonlocal reference_ordinal
        reference_ordinal += 1
        importer_id = files[package][source_role]
        path = importer_id.removeprefix("file:")
        reference_id = f"import:{path}:{line}:0:{reference_ordinal}"
        location = _location(path, line)
        graph["import_references"].append({
            "id": reference_id, "importer_id": importer_id, "kind": "from",
            "module": module, "name": name, "alias": None,
            "level": 1 if resolution == "unresolved" else 0,
            "location": location, "resolution": resolution,
            "target_id": target_id, "candidate_ids": [],
        })
        if resolution == "exact":
            graph["edges"].append({
                "id": f"imports:{reference_id}", "kind": "imports",
                "source_id": importer_id, "target_id": target_id,
                "location": location,
            })

    active_packages = package_labels[:-1]  # Last package is deliberately isolated.
    for package in package_labels:
        add_import(package, "source_a", files[package]["source_a"], "exact", "self", "source_a", 2)
        add_import(package, "source_a", files[package]["source_b"], "exact", "local", "source_b", 3)
        add_import(package, "source_a", None, "external", "requests", "Session", 4)
        add_import(package, "source_a", None, "unresolved", "missing", "Adapter", 5)
        if package in active_packages:
            successor = active_packages[(active_packages.index(package) + 1) % len(active_packages)]
            predecessor = active_packages[(active_packages.index(package) - 1) % len(active_packages)]
            target = files[successor]["sink"]
            add_import(package, "source_a", target, "exact", successor, "sink", 6)
            add_import(package, "source_a", target, "exact", successor, "sink", 7)
            add_import(package, "source_b", target, "exact", successor, "sink", 2)
            add_import(package, "source_b", files[predecessor]["sink"], "exact", predecessor, "sink", 3)

    graph["project"]["fingerprint"] = graph_fingerprint(graph)
    validate_graph_v1(graph)
    return graph


__all__ = ["build_representative_packages_v1"]
