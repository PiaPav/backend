"""Pure normalization, hashing and validation for Graph DTO v1."""
from __future__ import annotations

import hashlib
import json
from pathlib import PurePosixPath
from typing import Any, Mapping

NODE_KINDS = frozenset({"file", "module", "class", "field", "function", "method", "constant"})
CLASS_KINDS = frozenset({"class", "dataclass", "enum", "abstract"})
EDGE_KINDS = frozenset({"contains", "imports", "inherits", "field_type", "accesses_field", "calls", "awaits"})
RESOLUTION_STATUSES = frozenset({"exact", "ambiguous", "external", "dynamic", "unresolved"})
IMPORT_RESOLUTION_STATUSES = frozenset({"exact", "external", "unresolved"})
CONTROL_KINDS = frozenset({
    "if", "for", "async_for", "while", "try", "try_star", "match",
    "if_expression", "boolean", "comprehension", "exception_handler",
})
OCCURRENCE_KINDS = frozenset({"statement", "return", "raise", "await", "self_attribute"})
_COLLECTIONS = ("nodes", "edges", "callsites", "type_references", "import_references", "owner_structural_facts", "diagnostics")


def _key(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonicalize_graph(graph: Mapping[str, Any]) -> dict[str, Any]:
    """Return canonical DTO content; transitional ``body`` is never canonical."""
    result = {key: value for key, value in graph.items() if key != "body"}
    project = dict(result.get("project", {}))
    project.pop("fingerprint", None)
    result["project"] = project
    for name in _COLLECTIONS:
        if name in result:
            result[name] = sorted((dict(item) for item in result[name]), key=_key)
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


def _validate_complexity_facts(value: Any, where: str, path: str) -> None:
    if not isinstance(value, Mapping):
        _error(f"{where} must be an object")
    if set(value) != {"span", "is_async", "controls", "occurrences"}:
        _error(f"{where} has invalid fields")
    if type(value.get("is_async")) is not bool:
        _error(f"{where}.is_async must be a boolean")
    span = value.get("span")
    if not isinstance(span, Mapping) or set(span) != {"start", "end"}:
        _error(f"{where}.span is invalid")
    start, end = span.get("start"), span.get("end")
    _location(start, f"{where}.span.start"); _location(end, f"{where}.span.end")
    if start["path"] != path or end["path"] != path:
        _error(f"{where}.span paths must match the callable path")
    start_position = (start["line"], start["column"])
    end_position = (end["line"], end["column"])
    if end_position < start_position:
        _error(f"{where}.span is reversed")
    controls, occurrences = value.get("controls"), value.get("occurrences")
    if not isinstance(controls, list) or not isinstance(occurrences, list):
        _error(f"{where} controls and occurrences must be arrays")
    depths: list[int] = []
    for index, control in enumerate(controls):
        item_where = f"{where}.controls[{index}]"
        if not isinstance(control, Mapping): _error(f"{item_where} must be an object")
        allowed = {"kind", "parent_index", "location", "operand_count", "case_count", "filter_count", "expression"}
        if not set(control) <= allowed or not allowed - {"expression"} <= set(control):
            _error(f"{item_where} has invalid fields")
        kind, parent = control.get("kind"), control.get("parent_index")
        if kind not in CONTROL_KINDS: _error(f"{item_where}.kind is invalid")
        if parent is not None and (type(parent) is not int or parent < 0 or parent >= index):
            _error(f"{item_where}.parent_index must reference an earlier control")
        depths.append(0 if parent is None else depths[parent] + 1)
        location = control.get("location"); _location(location, f"{item_where}.location")
        position = (location["line"], location["column"])
        if location["path"] != path or not start_position <= position <= end_position:
            _error(f"{item_where}.location is outside the callable span")
        expected = {
            "operand_count": (kind == "boolean", 2),
            "case_count": (kind == "match", 1),
            "filter_count": (kind == "comprehension", 0),
        }
        for field, (used, minimum) in expected.items():
            cardinality = control.get(field)
            if (type(cardinality) is not int
                    or (used and cardinality < minimum)
                    or (not used and cardinality != 0)):
                _error(f"{item_where}.{field} is invalid")
        expression = control.get("expression")
        if kind == "exception_handler":
            if not isinstance(expression, str) or not expression: _error(f"{item_where}.expression is required")
        elif "expression" in control:
            _error(f"{item_where}.expression is not allowed")
    for index, occurrence in enumerate(occurrences):
        item_where = f"{where}.occurrences[{index}]"
        if not isinstance(occurrence, Mapping): _error(f"{item_where} must be an object")
        if not {"kind", "location"} <= set(occurrence) or not set(occurrence) <= {"kind", "location", "expression"}:
            _error(f"{item_where} has invalid fields")
        kind = occurrence.get("kind")
        if kind not in OCCURRENCE_KINDS: _error(f"{item_where}.kind is invalid")
        location = occurrence.get("location"); _location(location, f"{item_where}.location")
        position = (location["line"], location["column"])
        if location["path"] != path or not start_position <= position <= end_position:
            _error(f"{item_where}.location is outside the callable span")
        expression = occurrence.get("expression")
        if kind == "self_attribute" and (not isinstance(expression, str) or not expression):
            _error(f"{item_where}.expression is required")
        if "expression" in occurrence and kind not in {"raise", "self_attribute"}:
            _error(f"{item_where}.expression is not allowed")
        if kind == "raise" and "expression" in occurrence and (not isinstance(expression, str) or not expression):
            _error(f"{item_where}.expression is invalid")


def validate_graph_v1(graph: Mapping[str, Any], *, verify_fingerprint: bool = True) -> None:
    if not isinstance(graph, Mapping):
        _error("root must be an object")
    if type(graph.get("schema_version")) is not int or graph["schema_version"] != 1:
        _error(f"Unsupported schema_version {graph.get('schema_version')!r}")
    if type(graph.get("parser_semantics_version")) is not int or graph["parser_semantics_version"] not in {1, 2, 3, 4, 5, 6, 7}:
        _error(f"Unsupported parser_semantics_version {graph.get('parser_semantics_version')!r}")
    semantics = graph["parser_semantics_version"]
    if semantics == 5 and not isinstance(graph.get("body"), list):
        _error("body must be an array for parser semantics v5")
    if semantics == 6 and "body" in graph and not isinstance(graph["body"], list):
        _error("body must be an array when present for parser semantics v6")
    if semantics == 7 and "body" in graph:
        _error("body is not allowed for parser semantics v7")
    project = graph.get("project")
    if not isinstance(project, Mapping) or not isinstance(project.get("fingerprint"), str):
        _error("project.fingerprint is required")
    required_collections = tuple(
        name for name in _COLLECTIONS
        if (name != "type_references" or semantics >= 2)
        and (name != "import_references" or semantics >= 4)
        and (name != "owner_structural_facts" or semantics >= 6)
    )
    for name in required_collections:
        if not isinstance(graph.get(name), list):
            _error(f"{name} must be an array")
    nodes: dict[str, Mapping[str, Any]] = {}
    for index, node in enumerate(graph["nodes"]):
        if not isinstance(node, Mapping): _error(f"nodes[{index}] must be an object")
        identifier = node.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in nodes:
            _error(f"nodes[{index}].id is missing or duplicate")
        if node.get("kind") not in NODE_KINDS: _error(f"nodes[{index}].kind is invalid")
        if semantics < 5 and node.get("kind") == "constant":
            _error(f"nodes[{index}].kind is invalid")
        if not isinstance(node.get("qualified_name"), str): _error(f"nodes[{index}].qualified_name is required")
        _relative_path(node.get("path"), f"nodes[{index}].path")
        _location(node.get("location"), f"nodes[{index}].location")
        if node.get("kind") == "file" and identifier != f"file:{node.get('path')}":
            _error(f"nodes[{index}] file id must equal 'file:<path>'")
        nodes[identifier] = node
        if semantics >= 5:
            if node.get("kind") == "class":
                if node.get("class_kind") not in CLASS_KINDS:
                    _error(f"nodes[{index}].class_kind is invalid")
            elif "class_kind" in node:
                _error(f"nodes[{index}].class_kind is only allowed on classes")
        if semantics >= 3:
            if "synthetic" in node and type(node["synthetic"]) is not bool:
                _error(f"nodes[{index}].synthetic must be a boolean")
            if semantics >= 5 and "synthetic" in node and node.get("kind") != "method":
                _error(f"nodes[{index}].synthetic is only allowed on methods")
            callable_node = node.get("kind") in {"function", "method"}
            synthetic = node.get("synthetic") is True
            if callable_node and not synthetic:
                _validate_complexity_facts(node.get("complexity_facts"), f"nodes[{index}].complexity_facts", node["path"])
                if node["complexity_facts"]["span"]["start"] != node["location"]:
                    _error(f"nodes[{index}].complexity_facts span must start at node.location")
            elif "complexity_facts" in node:
                _error(f"nodes[{index}].complexity_facts is not allowed")
    contains: dict[str, str] = {}
    edges_by_id: dict[str, Mapping[str, Any]] = {}
    call_weights: dict[tuple[str, str, str], int] = {}
    for index, edge in enumerate(graph["edges"]):
        if not isinstance(edge, Mapping): _error(f"edges[{index}] must be an object")
        edge_id = edge.get("id")
        if not isinstance(edge_id, str) or not edge_id or edge_id in edges_by_id:
            _error(f"edges[{index}].id is missing or duplicate")
        edges_by_id[edge_id] = edge
        kind, source, target = edge.get("kind"), edge.get("source_id"), edge.get("target_id")
        if kind not in EDGE_KINDS: _error(f"edges[{index}].kind is invalid")
        if source not in nodes or target not in nodes: _error(f"edges[{index}] has an unknown node reference")
        if kind == "contains":
            if semantics >= 5 and nodes[target]["kind"] in {"file", "module"}:
                _error(f"edges[{index}] contains target must not be a canonical root")
            if target in contains: _error(f"node {target!r} has multiple containers")
            contains[target] = source
        if semantics >= 2:
            source_kind, target_kind = nodes[source]["kind"], nodes[target]["kind"]
            expected = {
                "inherits": ("class", "class"),
                "field_type": ("field", "class"),
                "accesses_field": ("method", "field"),
            }.get(kind)
            if expected is not None and (source_kind, target_kind) != expected:
                _error(f"edges[{index}] {kind} endpoints are invalid")
            if kind == "contains" and (source_kind, target_kind) not in {
                ("file", "class"), ("file", "function"),
                *((("file", "module"),) if semantics < 5 else ()),
                ("module", "class"), ("module", "function"),
                ("class", "method"), ("class", "field"),
                *(((("file", "constant"), ("module", "constant"))) if semantics >= 5 else ()),
            }:
                _error(f"edges[{index}] contains endpoints are invalid")
            if kind == "imports" and (
                source_kind not in {"file", "module"}
                or target_kind not in {"file", "module"}
            ):
                _error(f"edges[{index}] imports endpoints are invalid")
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
        if semantics >= 2 and nodes[node]["kind"] == "field":
            if parent is None or nodes[parent]["kind"] != "class":
                _error(f"field node {node!r} must belong to a class")
        if semantics >= 2 and nodes[node]["kind"] == "method":
            if parent is None or nodes[parent]["kind"] != "class":
                _error(f"method node {node!r} must belong to a class")
        if semantics >= 5:
            kind = nodes[node]["kind"]
            if nodes[node]["location"]["path"] != nodes[node]["path"]:
                _error(f"node {node!r} location path must match node path")
            if kind in {"file", "module"} and parent is not None:
                _error(f"canonical root node {node!r} must not have a parent")
            expected_owner = {"class": {"file", "module"}, "function": {"file", "module"},
                              "constant": {"file", "module"}, "method": {"class"},
                              "field": {"class"}}.get(kind)
            if expected_owner is not None and (parent is None or nodes[parent]["kind"] not in expected_owner):
                _error(f"node {node!r} has an invalid owner")
            if kind not in {"file", "module"}:
                root = node
                while root in contains:
                    root = contains[root]
                if nodes[root]["kind"] not in {"file", "module"}:
                    _error(f"node {node!r} has no owning root")
                root_path = nodes[root]["path"]
                if nodes[node]["path"] != root_path or nodes[node]["location"]["path"] != root_path:
                    _error(f"node {node!r} path must match its owning root")
    if semantics >= 6:
        expected_fact_owners = {
            identifier for identifier, node in nodes.items()
            if node["kind"] in {"file", "module"}
            or (node["kind"] in {"function", "method"} and node.get("synthetic") is not True)
        }
        seen_fact_owners: set[str] = set()
        for index, fact in enumerate(graph["owner_structural_facts"]):
            where = f"owner_structural_facts[{index}]"
            if not isinstance(fact, Mapping): _error(f"{where} must be an object")
            owner = fact.get("owner_id")
            if owner not in expected_fact_owners or owner in seen_fact_owners:
                _error(f"{where}.owner_id is invalid or duplicate")
            seen_fact_owners.add(owner)
            root = nodes[owner]["kind"] in {"file", "module"}
            expected_fields = {"owner_id", "call_occurrences"}
            if root: expected_fields.add("direct_import_occurrences")
            if set(fact) != expected_fields: _error(f"{where} has invalid fields")
            calls = fact.get("call_occurrences")
            if type(calls) is not int or calls < 0: _error(f"{where}.call_occurrences is invalid")
            if root:
                imports = fact.get("direct_import_occurrences")
                if not isinstance(imports, Mapping) or set(imports) != {"project_local", "non_project"}:
                    _error(f"{where}.direct_import_occurrences is invalid")
                if any(type(value) is not int or value < 0 for value in imports.values()):
                    _error(f"{where}.direct_import_occurrences counts are invalid")
        if seen_fact_owners != expected_fact_owners:
            _error("owner_structural_facts must contain exactly every structural owner")
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
    if semantics >= 4:
        import_edge_ids = {identifier for identifier, edge in edges_by_id.items()
                           if edge["kind"] == "imports"}
        referenced_import_edges: set[str] = set()
        import_reference_ids: set[str] = set()
        for index, reference in enumerate(graph["import_references"]):
            where = f"import_references[{index}]"
            if not isinstance(reference, Mapping):
                _error(f"{where} must be an object")
            required = {
                "id", "importer_id", "kind", "module", "name", "alias", "level",
                "location", "resolution", "target_id", "candidate_ids",
            }
            if set(reference) != required:
                _error(f"{where} has invalid fields")
            identifier = reference.get("id")
            if not isinstance(identifier, str) or not identifier or identifier in import_reference_ids:
                _error(f"{where}.id is missing or duplicate")
            import_reference_ids.add(identifier)
            importer = reference.get("importer_id")
            if importer not in nodes or nodes[importer]["kind"] not in {"file", "module"}:
                _error(f"{where}.importer_id is invalid")
            kind = reference.get("kind")
            if kind not in {"import", "from"}:
                _error(f"{where}.kind is invalid")
            module, name, alias, level = (
                reference.get("module"), reference.get("name"),
                reference.get("alias"), reference.get("level"),
            )
            if not isinstance(module, str) or not isinstance(name, str) or not name:
                _error(f"{where} module or name is invalid")
            if alias is not None and (not isinstance(alias, str) or not alias):
                _error(f"{where}.alias is invalid")
            if type(level) is not int or level < 0:
                _error(f"{where}.level is invalid")
            if kind == "import" and (module or level != 0):
                _error(f"{where} import kind cannot have module or level")
            if kind == "import" and name == "*":
                _error(f"{where} import kind cannot import a star")
            if kind == "from" and level == 0 and not module:
                _error(f"{where} absolute from kind requires a module")
            _location(reference.get("location"), f"{where}.location")
            if reference["location"]["path"] != nodes[importer]["path"]:
                _error(f"{where}.location path must match importer")
            status = reference.get("resolution")
            if status not in IMPORT_RESOLUTION_STATUSES:
                _error(f"{where}.resolution is invalid")
            if status == "external" and level != 0:
                _error(f"{where} external resolution must be absolute")
            if status == "unresolved" and level == 0:
                _error(f"{where} unresolved resolution must be relative")
            target, candidates = reference.get("target_id"), reference.get("candidate_ids")
            if candidates != []:
                _error(f"{where}.candidate_ids must be an empty array")
            edge_id = f"imports:{identifier}"
            if status == "exact":
                if target not in nodes or nodes[target]["kind"] not in {"file", "module"}:
                    _error(f"{where} exact resolution requires one file or module target")
                referenced_import_edges.add(edge_id)
                matching = edges_by_id.get(edge_id)
                if (matching is None or matching["kind"] != "imports"
                        or matching["source_id"] != importer
                        or matching["target_id"] != target
                        or matching.get("location") != reference["location"]):
                    _error(f"{where} exact resolution does not match its imports edge")
            elif target is not None:
                _error(f"{where} non-exact resolution cannot have a target")
        if import_edge_ids != referenced_import_edges:
            _error("imports edges do not match exact import references")
    if semantics >= 2:
        relation_edges = {
            (edge["kind"], edge["source_id"], edge["target_id"])
            for edge in graph["edges"] if edge["kind"] in {"inherits", "field_type"}
        }
        referenced_edges: set[tuple[str, str, str]] = set()
        reference_ids: set[str] = set()
        for index, reference in enumerate(graph["type_references"]):
            if not isinstance(reference, Mapping):
                _error(f"type_references[{index}] must be an object")
            identifier = reference.get("id")
            if not isinstance(identifier, str) or not identifier or identifier in reference_ids:
                _error(f"type_references[{index}].id is missing or duplicate")
            reference_ids.add(identifier)
            owner, role, status = reference.get("owner_id"), reference.get("role"), reference.get("resolution")
            if owner not in nodes or role not in {"base", "field_type"}:
                _error(f"type_references[{index}] owner or role is invalid")
            expected_owner = "class" if role == "base" else "field"
            if nodes[owner]["kind"] != expected_owner:
                _error(f"type_references[{index}].owner_id has invalid kind")
            if not isinstance(reference.get("expression"), str) or not reference["expression"]:
                _error(f"type_references[{index}].expression is required")
            _location(reference.get("location"), f"type_references[{index}].location")
            if status not in {"exact", "ambiguous", "external", "unresolved"}:
                _error(f"type_references[{index}].resolution is invalid")
            target, candidates = reference.get("target_id"), reference.get("candidate_ids", [])
            if not isinstance(candidates, list) or candidates != sorted(candidates) or len(candidates) != len(set(candidates)):
                _error(f"type_references[{index}].candidate_ids must be unique and sorted")
            if any(item not in nodes or nodes[item]["kind"] != "class" for item in candidates):
                _error(f"type_references[{index}].candidate_ids must reference classes")
            if status == "exact":
                if target not in nodes or nodes[target]["kind"] != "class" or candidates:
                    _error(f"type_references[{index}] exact resolution requires one class target")
                edge_kind = "inherits" if role == "base" else "field_type"
                referenced_edges.add((edge_kind, owner, target))
            elif status == "ambiguous":
                if target is not None or len(candidates) < 2:
                    _error(f"type_references[{index}] ambiguous resolution requires >=2 candidates")
            elif target is not None or candidates:
                _error(f"type_references[{index}] non-exact resolution cannot have targets")
        if relation_edges != referenced_edges:
            _error("typed relation edges do not match exact type references")
        for index, edge in enumerate(graph["edges"]):
            if edge["kind"] == "accesses_field":
                method_parent = nodes[edge["source_id"]].get("parent_id")
                field_parent = nodes[edge["target_id"]].get("parent_id")
                if method_parent != field_parent:
                    _error(f"edges[{index}] accesses_field endpoints must share an owning class")
    diagnostic_ids: set[str] = set()
    for index, diagnostic in enumerate(graph["diagnostics"]):
        if not isinstance(diagnostic, Mapping): _error(f"diagnostics[{index}] must be an object")
        identifier = diagnostic.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in diagnostic_ids:
            _error(f"diagnostics[{index}].id is missing or duplicate")
        diagnostic_ids.add(identifier)
    if verify_fingerprint and project["fingerprint"] != graph_fingerprint(graph):
        _error("project.fingerprint does not match canonical content")
