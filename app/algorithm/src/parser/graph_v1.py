"""Projection of analyzed parser facts into the transitional Graph DTO v1."""
from __future__ import annotations

from typing import Any
import json

from graph_dto import graph_fingerprint, validate_graph_v1
from .logic.models import ModuleInfo
from .logic.project_index import ProjectIndex


def _file_id(module: ModuleInfo) -> str:
    return f"file:{module.relative_path.as_posix()}"


def _location(module: ModuleInfo, line: int | None, column: int | None) -> dict[str, Any]:
    return {"path": module.relative_path.as_posix(), "line": line or 1, "column": column or 0}


def build_graph_v1(index: ProjectIndex, body: list[dict[str, Any]]) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    module_files = {id(module): _file_id(module) for module in index.modules}
    effective_files = {name: module_files[id(module)] for name, module in index.by_module.items()}
    for module in index.modules:
        file_id = module_files[id(module)]
        path = module.relative_path.as_posix()
        nodes.append({"id": file_id, "kind": "file", "qualified_name": module.module,
                      "parent_id": None, "path": path, "location": _location(module, 1, 0)})
        for class_info in module.classes:
            class_id = f"class:{path}:{class_info.line or 1}:{class_info.column or 0}:{class_info.name}"
            nodes.append({"id": class_id, "kind": "class", "qualified_name": f"{module.module}.{class_info.name}".strip("."),
                          "parent_id": file_id, "path": path, "location": _location(module, class_info.line, class_info.column)})
            edges.append({"id": f"contains:{file_id}->{class_id}", "kind": "contains", "source_id": file_id, "target_id": class_id})
            for method in class_info.methods:
                method_id = f"method:{path}:{method.line or 1}:{method.column or 0}:{class_info.name}.{method.name}"
                nodes.append({"id": method_id, "kind": "method", "qualified_name": f"{module.module}.{class_info.name}.{method.name}".strip("."),
                              "parent_id": class_id, "path": path, "location": _location(module, method.line, method.column)})
                edges.append({"id": f"contains:{class_id}->{method_id}", "kind": "contains", "source_id": class_id, "target_id": method_id})
        for function in module.functions:
            function_id = f"function:{path}:{function.line or 1}:{function.column or 0}:{function.name}"
            nodes.append({"id": function_id, "kind": "function", "qualified_name": f"{module.module}.{function.name}".strip("."),
                          "parent_id": file_id, "path": path, "location": _location(module, function.line, function.column)})
            edges.append({"id": f"contains:{file_id}->{function_id}", "kind": "contains", "source_id": file_id, "target_id": function_id})
        for position, imported in enumerate(module.imports):
            target = effective_files.get(imported.local_module or "")
            if target is not None:
                edges.append({"id": f"imports:{file_id}->{target}:{position}", "kind": "imports",
                              "source_id": file_id, "target_id": target,
                              "location": _location(module, imported.line, imported.column)})
    diagnostics = [
        {"id": f"shadowed_module:{name}:{shadowed.relative_path.as_posix()}",
         "kind": "shadowed_module", "status": "warning", "module": name,
         "path": shadowed.relative_path.as_posix(), "effective_path": effective.relative_path.as_posix()}
        for name, shadowed, effective in index.shadowed_modules
    ]
    diagnostics.append({"id": "semantic_callsites_transition", "kind": "incomplete_semantic_resolution",
                        "status": "transition", "message": "Canonical callsites and call edges are not emitted yet; use the legacy body mirror."})
    graph: dict[str, Any] = {"schema_version": 1, "parser_semantics_version": 1,
                             "project": {"fingerprint": ""}, "nodes": nodes, "edges": edges,
                             "callsites": [], "diagnostics": diagnostics, "body": body}
    sort_key = lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    for collection in ("nodes", "edges", "callsites", "diagnostics"):
        graph[collection].sort(key=sort_key)
    graph["project"]["fingerprint"] = graph_fingerprint(graph)
    validate_graph_v1(graph)
    return graph
