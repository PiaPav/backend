"""Projection of analyzed parser facts into the transitional Graph DTO v1."""
from __future__ import annotations

from typing import Any
import json
from collections import Counter

from graph_dto import PARSER_SEMANTICS_VERSION, graph_fingerprint, validate_graph_v1
from .logic.models import FunctionComplexityFacts, ModuleInfo
from .logic.project_index import ProjectIndex


def _file_id(module: ModuleInfo) -> str:
    return f"file:{module.relative_path.as_posix()}"


def _location(module: ModuleInfo, line: int | None, column: int | None) -> dict[str, Any]:
    return {"path": module.relative_path.as_posix(), "line": line or 1, "column": column or 0}


def _complexity_facts(module: ModuleInfo, facts: FunctionComplexityFacts) -> dict[str, Any]:
    def location(line: int, column: int) -> dict[str, Any]:
        return _location(module, line, column)

    return {
        "span": {
            "start": location(facts.start_line, facts.start_column),
            "end": location(facts.end_line, facts.end_column),
        },
        "is_async": facts.is_async,
        "controls": [
            {
                "kind": item.kind,
                "parent_index": item.parent_index,
                "location": location(item.line, item.column),
                "operand_count": item.operand_count,
                "case_count": item.case_count,
                "filter_count": item.filter_count,
                **({"expression": item.expression} if item.expression is not None else {}),
            }
            for item in facts.controls
        ],
        "occurrences": [
            {
                "kind": item.kind,
                "location": location(item.line, item.column),
                **({"expression": item.expression} if item.expression is not None else {}),
            }
            for item in facts.occurrences
        ],
    }


def build_graph_v1(index: ProjectIndex, body: list[dict[str, Any]]) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    callsites: list[dict[str, Any]] = []
    type_references: list[dict[str, Any]] = []
    import_references: list[dict[str, Any]] = []
    declaration_ids: dict[int, str] = {}
    target_ids: dict[tuple[str, int], str] = {}
    module_files = {id(module): _file_id(module) for module in index.modules}
    effective_files = {name: module_files[id(module)] for name, module in index.by_module.items()}
    required_constructors = {
        call.target
        for module in index.modules
        for call in (
            module.canonical_callsites
            + [item for function in module.functions for item in function.canonical_callsites]
            + [item for class_info in module.classes for method in class_info.methods for item in method.canonical_callsites]
        )
        if call.resolution == "exact" and call.target and call.target[0] == "constructor"
    }
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
            declaration_ids[id(class_info)] = class_id
            for field in class_info.fields:
                field_id = f"field:{path}:{field.line or 1}:{field.column or 0}:{class_info.name}.{field.name}"
                nodes.append({"id": field_id, "kind": "field",
                              "qualified_name": f"{module.module}.{class_info.name}.{field.name}".strip("."),
                              "parent_id": class_id, "path": path,
                              "location": _location(module, field.line, field.column)})
                edges.append({"id": f"contains:{class_id}->{field_id}", "kind": "contains",
                              "source_id": class_id, "target_id": field_id})
                declaration_ids[id(field)] = field_id
            for method in class_info.methods:
                method_id = f"method:{path}:{method.line or 1}:{method.column or 0}:{class_info.name}.{method.name}"
                nodes.append({"id": method_id, "kind": "method", "qualified_name": f"{module.module}.{class_info.name}.{method.name}".strip("."),
                              "parent_id": class_id, "path": path, "location": _location(module, method.line, method.column),
                              "complexity_facts": _complexity_facts(module, method.complexity_facts)})
                edges.append({"id": f"contains:{class_id}->{method_id}", "kind": "contains", "source_id": class_id, "target_id": method_id})
                declaration_ids[id(method)] = method_id
                target_ids[("method", id(method))] = method_id
            constructor_key = ("constructor", id(class_info))
            if (
                constructor_key in required_constructors
                and not any(method.name == "__init__" for method in class_info.methods)
            ):
                method_id = f"method:{path}:{class_info.line or 1}:{class_info.column or 0}:{class_info.name}.__init__:synthetic"
                nodes.append({"id": method_id, "kind": "method",
                              "qualified_name": f"{module.module}.{class_info.name}.__init__".strip("."),
                              "parent_id": class_id, "path": path,
                              "location": _location(module, class_info.line, class_info.column), "synthetic": True})
                edges.append({"id": f"contains:{class_id}->{method_id}", "kind": "contains",
                              "source_id": class_id, "target_id": method_id})
                target_ids[constructor_key] = method_id
        for function in module.functions:
            function_id = f"function:{path}:{function.line or 1}:{function.column or 0}:{function.name}"
            nodes.append({"id": function_id, "kind": "function", "qualified_name": f"{module.module}.{function.name}".strip("."),
                          "parent_id": file_id, "path": path, "location": _location(module, function.line, function.column),
                          "complexity_facts": _complexity_facts(module, function.complexity_facts)})
            edges.append({"id": f"contains:{file_id}->{function_id}", "kind": "contains", "source_id": file_id, "target_id": function_id})
            declaration_ids[id(function)] = function_id
            target_ids[("function", id(function))] = function_id
        for imported in module.canonical_imports:
            target = effective_files.get(imported.local_module or "")
            resolution = "exact" if target is not None else imported.resolution
            reference_id = (
                f"import:{path}:{imported.statement_line or imported.line or 1}:"
                f"{imported.statement_column or 0}:{imported.line or 1}:"
                f"{imported.column or 0}:{imported.alias_index}"
            )
            import_references.append({
                "id": reference_id, "importer_id": file_id,
                "kind": "from" if imported.module or imported.level else "import",
                "module": imported.module, "name": imported.object_name,
                "alias": imported.asname, "level": imported.level,
                "location": _location(module, imported.line, imported.column),
                "resolution": resolution, "target_id": target, "candidate_ids": [],
            })
            if resolution == "exact":
                edges.append({"id": f"imports:{reference_id}", "kind": "imports",
                               "source_id": file_id, "target_id": target,
                                "location": _location(module, imported.line, imported.column)})
    reference_ordinal = 0
    for module in index.modules:
        for fact in module.type_references:
            reference_ordinal += 1
            owner_id = declaration_ids[id(fact.owner)]
            target_id = declaration_ids.get(id(fact.target)) if fact.target is not None else None
            resolution = "exact" if fact.resolution == "exact" and target_id else fact.resolution
            if fact.resolution == "exact" and target_id is None:
                resolution = "unresolved"
            reference = {
                "id": f"type_reference:{module.relative_path.as_posix()}:{fact.line or 1}:{fact.column or 0}:{reference_ordinal}",
                "owner_id": owner_id, "role": fact.role, "expression": fact.expression,
                "location": _location(module, fact.line, fact.column), "resolution": resolution,
                "target_id": target_id if resolution == "exact" else None,
                "candidate_ids": sorted({declaration_ids[id(item)] for item in fact.candidates
                                         if id(item) in declaration_ids}),
            }
            type_references.append(reference)
            if resolution == "exact":
                kind = "inherits" if fact.role == "base" else "field_type"
                edges.append({"id": f"{kind}:{owner_id}->{target_id}:{reference_ordinal}",
                              "kind": kind, "source_id": owner_id, "target_id": target_id})
        for ordinal, access in enumerate(module.field_accesses, 1):
            source_id = declaration_ids[id(access.method)]
            target_id = declaration_ids[id(access.field)]
            edges.append({"id": f"accesses_field:{source_id}->{target_id}:{access.line or 1}:{access.column or 0}:{ordinal}",
                          "kind": "accesses_field", "source_id": source_id, "target_id": target_id,
                          "location": _location(module, access.line, access.column)})
    aggregates: Counter[tuple[str, str, str]] = Counter()
    ordinal = 0
    for module in index.modules:
        owners = [(module_files[id(module)], module.canonical_callsites)]
        owners.extend((declaration_ids[id(function)], function.canonical_callsites) for function in module.functions)
        owners.extend(
            (declaration_ids[id(method)], method.canonical_callsites)
            for class_info in module.classes
            for method in class_info.methods
        )
        for caller_id, facts in owners:
            for fact in facts:
                ordinal += 1
                target_id = target_ids.get(fact.target) if fact.target else None
                resolution = "exact" if fact.resolution == "exact" and target_id else fact.resolution
                if fact.resolution == "exact" and target_id is None:
                    resolution = "unresolved"
                callsite = {
                    "id": f"call:{module.relative_path.as_posix()}:{fact.line or 1}:{fact.column or 0}:{ordinal}",
                    "caller_id": caller_id,
                    "expression": fact.expression,
                    "location": _location(module, fact.line, fact.column),
                    "syntactic_depth": fact.syntactic_depth,
                    "resolution": resolution,
                    "target_id": target_id if resolution == "exact" else None,
                    "candidate_ids": [],
                    "awaited": fact.awaited,
                }
                callsites.append(callsite)
                if resolution == "exact":
                    kind = "awaits" if fact.awaited else "calls"
                    aggregates[(caller_id, target_id, kind)] += 1
    for (source_id, target_id, kind), weight in aggregates.items():
        edges.append({"id": f"{kind}:{source_id}->{target_id}", "kind": kind,
                      "source_id": source_id, "target_id": target_id, "weight": weight})

    diagnostics = [
        {"id": f"shadowed_module:{name}:{shadowed.relative_path.as_posix()}",
         "kind": "shadowed_module", "status": "warning", "module": name,
         "path": shadowed.relative_path.as_posix(), "effective_path": effective.relative_path.as_posix()}
        for name, shadowed, effective in index.shadowed_modules
    ]
    graph: dict[str, Any] = {"schema_version": 1, "parser_semantics_version": PARSER_SEMANTICS_VERSION,
                              "project": {"fingerprint": ""}, "nodes": nodes, "edges": edges,
                              "callsites": callsites, "type_references": type_references,
                              "import_references": import_references,
                              "diagnostics": diagnostics, "body": body}
    sort_key = lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    # Nodes are emitted in deterministic containment order (file before its
    # declarations).  Sorting their complete JSON used to make newly added
    # optional payloads silently alter this public order.
    for collection in ("edges", "callsites", "type_references", "import_references", "diagnostics"):
        graph[collection].sort(key=sort_key)
    graph["project"]["fingerprint"] = graph_fingerprint(graph)
    validate_graph_v1(graph)
    return graph
