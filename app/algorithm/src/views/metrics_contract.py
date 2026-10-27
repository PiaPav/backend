"""Standalone contract for Metrics View DTO v1."""
from __future__ import annotations

import hashlib
import json
import math
import re
from copy import deepcopy
from typing import Any, Mapping

from .registry import metrics_profile_metadata

_HEX = re.compile(r"[0-9a-f]{64}\Z")
_ROOT = {"artifact_kind", "view_schema_version", "profile", "source", "completeness", "payload", "view_fingerprint"}
SIZE = ("directories", "files", "classes", "abstract_classes", "dataclasses", "functions", "methods", "fields", "constants")
ACTIVITY = ("calls", "local_imports", "external_imports", "average_calls_per_callable", "average_calls_per_call_owner", "average_methods_per_class")
DEPENDENCY = ("nodes", "edges", "density", "average_fan_in", "average_fan_out", "weakly_connected_components", "isolated_files", "cyclic_components", "highest_fan_in", "highest_fan_out")
ARCHITECTURE = ("packages", "package_edges", "cyclic_package_components", "articulation_files", "bridge_dependencies")
CALL_OVERVIEW = ("nodes", "edges", "callsites_in_local_edges", "external_or_builtin_callsites", "unresolved_callsites", "unresolved_or_external_callsites", "local_resolution_rate", "classified_callsite_rate", "maximum_call_chain_depth", "maximum_syntactic_call_nesting")
QUALITY = ("analyzed_callables", "average_cyclomatic_complexity", "average_cognitive_complexity", "average_lines_per_callable", "maximum_control_nesting", "high_complexity_callables", "largest_callables", "deeply_nested_callables", "async", "exceptions")
OBJECT_ORIENTED = ("classes_analyzed", "highest_weighted_method_complexity", "highest_class_coupling", "largest_response_sets", "lowest_cohesion", "deepest_inheritance", "most_direct_children", "classes")
CALL_GRAPH = CALL_OVERVIEW + ("heaviest_edges", "entrypoints", "leaf_callables", "isolated_callables", "highest_fan_in", "highest_fan_out", "maximum_transitive_reach", "longest_call_chain", "deepest_nested_call_owners", "recursive_components", "pagerank_top", "betweenness_top", "risk_top", "node_kinds")

ROUNDING_POLICY = {"kind": "decimal_places", "places": 4, "applies_to": "ratio_metrics"}
THRESHOLD_POLICY = {
    "descriptor_version": 1,
    "high_complexity": {"cyclomatic_gte": 10, "cognitive_gte": 15, "operator": "or"},
    "deep_nesting": {"nesting_gte": 4},
    "largest_callables": {"limit": 10, "tie_policy": "fixed_size", "ordering": ["lines descending", "node ascending"]},
}
DEFINITIONS = [
    {"id": "activity_call_owner", "population": "hybrid activity call owners: non-synthetic functions and methods plus roots with structural call_occurrences greater than zero", "includes": ["roots with structural call occurrences", "non-synthetic functions", "non-synthetic methods"], "excludes": ["synthetic methods", "roots without structural call occurrences"]},
    {"id": "call_graph_owner", "population": "call-graph owners: all function and method nodes plus roots with a callsite or an outgoing canonical call edge", "includes": ["functions", "methods including synthetic methods", "roots with callsites", "roots with outgoing canonical call edges"], "excludes": ["roots without callsites or outgoing canonical call edges"]},
    {"id": "callable", "population": "non-synthetic functions and methods", "includes": ["functions", "non-synthetic methods"], "excludes": ["roots", "synthetic methods"]},
    {"id": "callsite", "population": "callsite occurrences owned by included call_graph_owner nodes", "includes": ["local", "external", "unresolved occurrences"], "excludes": ["calls outside call-graph owners"]},
    {"id": "dependency_pair", "population": "ordered distinct root pairs", "includes": ["ordered pairs of distinct roots"], "excludes": ["self pairs"]},
    {"id": "package_class", "population": "classes owned directly by roots in the package", "includes": ["direct-root-owned package classes"], "excludes": ["nested or indirectly owned classes"]},
    {"id": "package_neighbour", "population": "unique package neighbours", "includes": ["distinct incoming and outgoing package neighbours"], "excludes": ["duplicate file pairs", "self package pairs"]},
    {"id": "root", "population": "canonical file and module roots", "includes": ["file roots", "module roots"], "excludes": ["declarations"]},
]

OBJECT_TOPOLOGY_POLICY = {
    "descriptor_version": 1,
    "adjacency": "canonical internal exact unique adjacency",
    "call_relations": "calls and awaits are unweighted; occurrence multiplicity does not affect CBO or RFC",
    "ownership": "direct declaration ownership",
    "synthetic_methods": "excluded as declared methods and callers; exact synthetic method targets may count",
    "standalone_function_targets": "may count in RFC",
    "non_exact_relations": "absence does not prove absence of a runtime relation",
}
OBJECT_INTERPRETATION_POLICY = {
    "descriptor_version": 1,
    "class_label": "display label, not canonical identifier",
    "lcom": {
        "denominator": "unordered pairs of directly declared non-synthetic methods",
        "null_when": ["fewer than two eligible methods", "no directly declared fields"],
        "zero_is_not_null": True,
    },
    "dit_null": "internal inheritance cycle",
}


def _bindings(profile: str) -> list[dict[str, Any]]:
    if profile == "metrics.quality":
        return [
            {"metric": f"metrics.code_quality.{metric}", "denominator": "metrics.code_quality.analyzed_callables", "zero_denominator_result": 0.0}
            for metric in ("average_cognitive_complexity", "average_cyclomatic_complexity", "average_lines_per_callable")
        ]
    if profile == "metrics.objects":
        return [{
            "metric": "metrics.object_oriented.classes[*].lcom",
            "denominator": "unordered pairs of directly declared non-synthetic methods",
            "null_result_when": "fewer than two eligible methods or no directly declared fields",
        }]
    common = [
        {"metric": "metrics.dependency_graph.density", "denominator": "ordered distinct root pairs: n*(n-1)", "zero_denominator_result": 0.0},
        {"metric": "metrics.dependency_graph.average_fan_in", "denominator": "dependency graph roots", "zero_denominator_result": 0.0},
        {"metric": "metrics.dependency_graph.average_fan_out", "denominator": "dependency graph roots", "zero_denominator_result": 0.0},
    ]
    if profile == "metrics.architecture":
        return sorted(common + [
            {"metric": "metrics.architecture.packages[*].abstractness", "denominator": "row field classes (direct-root-owned package classes)", "zero_denominator_result": 0.0},
            {"metric": "metrics.architecture.packages[*].instability", "denominator": "row sum afferent_coupling + efferent_coupling (unique package neighbours)", "zero_denominator_result": 0.0},
        ], key=lambda row: row["metric"])
    return sorted(common + [
        {"metric": "metrics.activity.average_calls_per_callable", "denominator": "metrics.size.functions + metrics.size.methods", "zero_denominator_result": 0.0},
        {"metric": "metrics.activity.average_calls_per_call_owner", "denominator": "activity_call_owner (not materialized)", "zero_denominator_result": 0.0},
        {"metric": "metrics.activity.average_methods_per_class", "denominator": "metrics.size.classes", "zero_denominator_result": 0.0},
        {"metric": "metrics.call_graph.classified_callsite_rate", "denominator": "local + external + unresolved callsite occurrences", "zero_denominator_result": 0.0},
        {"metric": "metrics.call_graph.local_resolution_rate", "denominator": "local + external + unresolved callsite occurrences", "zero_denominator_result": 0.0},
    ], key=lambda row: row["metric"])


def population_metadata(profile: str) -> dict[str, Any]:
    if profile == "metrics.quality":
        definitions = [row for row in DEFINITIONS if row["id"] == "callable"]
    elif profile == "metrics.objects":
        definitions = [
            {"id": "class", "population": "canonical class nodes", "includes": ["all canonical classes"], "excludes": []},
            {"id": "declared_method", "population": "methods directly owned by a class", "includes": ["non-synthetic methods"], "excludes": ["synthetic methods", "inherited methods"]},
            {"id": "declared_field", "population": "fields directly owned by a class", "includes": ["directly declared fields"], "excludes": ["inherited fields"]},
            {"id": "callable_target", "population": "exact canonical function or method targets", "includes": ["functions", "methods including synthetic targets"], "excludes": ["non-exact targets"], "materialization": "complete callable target population not_materialized"},
        ]
    else:
        definitions = DEFINITIONS
    return {"descriptor_version": 1, "rounding_policy": deepcopy(ROUNDING_POLICY), "definitions": deepcopy(definitions), "metric_denominators": _bindings(profile)}


PACKAGE_GROUPING = {
    "descriptor_version": 1,
    "path_policy": {"separator": "/", "package": "first POSIX path segment", "root_package": "<root>", "root_condition": "path contains no '/'"},
    "file_edges": {"kind": "exact non-self distinct file pairs"},
    "package_edges": {"kind": "distinct cross-package pairs"},
}


def _error(message: str) -> None:
    raise ValueError(f"Invalid Metrics View DTO v1: {message}")


def _obj(value: Any, fields: set[str], where: str, *, exact: bool = True) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or (set(value) != fields if exact else not fields <= set(value)):
        _error(f"{where} has invalid fields")
    return value


def _typed_tree_equal(value: Any, expected: Any) -> bool:
    """Compare JSON-shaped contract data without bool/numeric coercion."""
    if type(value) is not type(expected):
        return False
    if isinstance(expected, dict):
        return (value.keys() == expected.keys()
                and all(_typed_tree_equal(value[key], expected[key]) for key in expected))
    if isinstance(expected, list):
        return (len(value) == len(expected)
                and all(_typed_tree_equal(item, expected_item)
                        for item, expected_item in zip(value, expected)))
    return value == expected


def _count(value: Any, where: str) -> None:
    if type(value) is not int or value < 0: _error(f"{where} must be a nonnegative integer")


def _number(value: Any, where: str, *, rate: bool = False) -> None:
    if type(value) is not float or not math.isfinite(value) or value < 0 or (rate and value > 1):
        _error(f"{where} must be a finite nonnegative {'rate' if rate else 'number'}")


def _sorted_strings(value: Any, where: str) -> None:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value) or value != sorted(set(value)):
        _error(f"{where} must contain unique sorted strings")


def _sorted_groups(value: Any, where: str, *, min_size: int = 1) -> None:
    if (not isinstance(value, list)
            or any(not isinstance(row, list) or len(row) < min_size
                   or any(not isinstance(item, str) or not item for item in row)
                   or row != sorted(set(row)) for row in value)
            or value != sorted(value) or len(value) != len({tuple(row) for row in value})):
        _error(f"{where} must contain unique canonically sorted groups")


def _string(value: Any, where: str, *, nonempty: bool = False) -> None:
    if not isinstance(value, str) or nonempty and not value:
        _error(f"{where} must be a{' nonempty' if nonempty else ''} string")


def _string_count_map(value: Any, where: str) -> None:
    item = _obj(value, set(), where, exact=False)
    if list(item) != sorted(item) or any(not isinstance(key, str) or not key for key in item):
        _error(f"{where} must have canonically sorted string keys")
    for key, count in item.items(): _count(count, f"{where}.{key}")


def _rows(value: Any, fields: set[str], where: str, validator: Any, *, exact: bool = False) -> list[Mapping[str, Any]]:
    if not isinstance(value, list): _error(f"{where} must be an array")
    result = []
    for index, raw in enumerate(value):
        row = _obj(raw, fields, f"{where}[{index}]", exact=exact); validator(row, f"{where}[{index}]"); result.append(row)
    return result


def _validate_dependency(value: Any, where: str, *, exact: bool, details: bool) -> None:
    item = _obj(value, set(DEPENDENCY) if details else set(DEPENDENCY[:6]), where, exact=exact)
    for key in ("nodes", "edges", "weakly_connected_components"): _count(item[key], f"{where}.{key}")
    for key in ("density", "average_fan_in", "average_fan_out"): _number(item[key], f"{where}.{key}", rate=key == "density")
    if details:
        _sorted_strings(item["isolated_files"], f"{where}.isolated_files"); _sorted_groups(item["cyclic_components"], f"{where}.cyclic_components", min_size=2)
        for key in ("highest_fan_in", "highest_fan_out"):
            peak = _obj(item[key], {"degree", "files"}, f"{where}.{key}", exact=exact); _count(peak["degree"], f"{where}.{key}.degree"); _sorted_strings(peak["files"], f"{where}.{key}.files")


def _validate_architecture(value: Any, where: str, *, exact: bool) -> None:
    item = _obj(value, set(ARCHITECTURE), where, exact=exact)
    packages = item["packages"]
    if not isinstance(packages, list): _error(f"{where}.packages must be an array")
    names = []
    fields = {"package", "files", "classes", "abstract_classes", "afferent_coupling", "efferent_coupling", "instability", "abstractness", "distance_from_main_sequence"}
    for index, row_value in enumerate(packages):
        row = _obj(row_value, fields, f"{where}.packages[{index}]", exact=exact); names.append(row["package"])
        if not isinstance(row["package"], str): _error("package name must be a string")
        for key in ("files", "classes", "abstract_classes", "afferent_coupling", "efferent_coupling"): _count(row[key], f"package.{key}")
        for key in ("instability", "abstractness", "distance_from_main_sequence"): _number(row[key], f"package.{key}", rate=True)
    if names != sorted(set(names)): _error(f"{where}.packages must be uniquely sorted")
    _count(item["package_edges"], f"{where}.package_edges"); _sorted_groups(item["cyclic_package_components"], f"{where}.cyclic_package_components", min_size=2); _sorted_strings(item["articulation_files"], f"{where}.articulation_files")
    bridges = item["bridge_dependencies"]
    if (not isinstance(bridges, list)
            or any(not isinstance(row, list) or len(row) != 2
                   or any(not isinstance(endpoint, str) or not endpoint for endpoint in row)
                   or row[0] == row[1] or row != sorted(row) for row in bridges)
            or bridges != sorted(bridges) or len(bridges) != len({tuple(row) for row in bridges})):
        _error(f"{where}.bridge_dependencies is not canonical")


def _validate_quality(value: Any, where: str, *, exact: bool = False, expected_population: int | None = None) -> None:
    item = _obj(value, set(QUALITY), where, exact=exact)
    _count(item["analyzed_callables"], f"{where}.analyzed_callables")
    for key in ("average_cyclomatic_complexity", "average_cognitive_complexity", "average_lines_per_callable"):
        _number(item[key], f"{where}.{key}")
    _count(item["maximum_control_nesting"], f"{where}.maximum_control_nesting")

    def complexity(row: Mapping[str, Any], row_where: str) -> None:
        _string(row["node"], f"{row_where}.node")
        for key in ("cyclomatic", "cognitive", "lines", "nesting"): _count(row[key], f"{row_where}.{key}")
        if row["cyclomatic"] < 1 or row["lines"] < 1: _error(f"{row_where} has impossible complexity or line count")
    rows = _rows(item["high_complexity_callables"], {"node", "cyclomatic", "cognitive", "lines", "nesting"}, f"{where}.high_complexity_callables", complexity, exact=exact)
    if rows != sorted(rows, key=lambda row: (-row["cyclomatic"], -row["cognitive"], row["node"])): _error(f"{where}.high_complexity_callables is not canonical")
    if any(row["cyclomatic"] < 10 and row["cognitive"] < 15 for row in rows): _error(f"{where}.high_complexity_callables violates thresholds")

    def node_count(row: Mapping[str, Any], row_where: str, key: str) -> None:
        _string(row["node"], f"{row_where}.node"); _count(row[key], f"{row_where}.{key}")
    largest = _rows(item["largest_callables"], {"node", "lines"}, f"{where}.largest_callables", lambda row, place: node_count(row, place, "lines"), exact=exact)
    nested = _rows(item["deeply_nested_callables"], {"node", "nesting"}, f"{where}.deeply_nested_callables", lambda row, place: node_count(row, place, "nesting"), exact=exact)
    if largest != sorted(largest, key=lambda row: (-row["lines"], row["node"])) or nested != sorted(nested, key=lambda row: (-row["nesting"], row["node"])): _error(f"{where} rankings are not canonical")
    if any(row["lines"] < 1 for row in largest) or any(row["nesting"] < 4 for row in nested): _error(f"{where} rankings violate thresholds")
    for rows_value, name in ((rows, "high_complexity_callables"), (largest, "largest_callables"), (nested, "deeply_nested_callables")):
        if len(rows_value) != len({row["node"] for row in rows_value}): _error(f"{where}.{name} contains duplicate nodes")
    async_ = _obj(item["async"], {"functions", "without_await"}, f"{where}.async", exact=exact)
    _count(async_["functions"], f"{where}.async.functions"); _sorted_strings(async_["without_await"], f"{where}.async.without_await")
    exceptions = _obj(item["exceptions"], {"raise_statements", "callables_raising", "raised_types", "caught_types", "broad_handlers"}, f"{where}.exceptions", exact=exact)
    _count(exceptions["raise_statements"], f"{where}.exceptions.raise_statements"); _count(exceptions["callables_raising"], f"{where}.exceptions.callables_raising")
    _string_count_map(exceptions["raised_types"], f"{where}.exceptions.raised_types"); _string_count_map(exceptions["caught_types"], f"{where}.exceptions.caught_types")
    handlers = _rows(exceptions["broad_handlers"], {"node", "count"}, f"{where}.exceptions.broad_handlers", lambda row, place: node_count(row, place, "count"), exact=exact)
    if any(row["count"] < 1 for row in handlers): _error(f"{where}.exceptions.broad_handlers contains a zero count")
    if handlers != sorted(handlers, key=lambda row: (-row["count"], row["node"])) or len(handlers) != len({row["node"] for row in handlers}): _error(f"{where}.exceptions.broad_handlers is not canonical")
    population = item["analyzed_callables"]
    if expected_population is not None and population != expected_population: _error(f"{where}.analyzed_callables does not match size functions plus methods")
    if len(largest) != min(population, 10): _error(f"{where}.largest_callables has inconsistent length")
    if (len(rows) > population or len(nested) > population or len(handlers) > population
            or async_["functions"] > population or len(async_["without_await"]) > async_["functions"]
            or exceptions["callables_raising"] > population):
        _error(f"{where} contains counts outside the callable population")
    maximum_nesting = item["maximum_control_nesting"]
    if ((maximum_nesting < 4 and nested)
            or (maximum_nesting >= 4 and (not nested or nested[0]["nesting"] != maximum_nesting))):
        _error(f"{where}.deeply_nested_callables is inconsistent with maximum_control_nesting")
    if population == 0 and (rows or largest or nested or item["maximum_control_nesting"] != 0
                            or any(item[key] != 0.0 for key in ("average_cyclomatic_complexity", "average_cognitive_complexity", "average_lines_per_callable"))
                            or async_["functions"] != 0 or async_["without_await"]
                            or exceptions["raise_statements"] != 0 or exceptions["callables_raising"] != 0
                            or exceptions["raised_types"] or exceptions["caught_types"] or handlers):
        _error(f"{where} empty population is inconsistent")


def _validate_object_oriented(value: Any, where: str, *, exact: bool = False,
                              expected_population: int | None = None) -> None:
    item = _obj(value, set(OBJECT_ORIENTED), where, exact=exact); _count(item["classes_analyzed"], f"{where}.classes_analyzed")
    fields = {"class", "wmc", "cbo", "rfc", "lcom", "dit", "noc"}
    def class_row(row: Mapping[str, Any], place: str) -> None:
        _string(row["class"], f"{place}.class", nonempty=True)
        for key in ("wmc", "cbo", "rfc", "noc"): _count(row[key], f"{place}.{key}")
        if row["dit"] is not None: _count(row["dit"], f"{place}.dit")
        if row["lcom"] is not None: _number(row["lcom"], f"{place}.lcom", rate=True)
    rankings = {"highest_weighted_method_complexity": "wmc", "highest_class_coupling": "cbo", "largest_response_sets": "rfc", "lowest_cohesion": "lcom", "deepest_inheritance": "dit", "most_direct_children": "noc"}
    for name, key in rankings.items():
        rows = _rows(item[name], fields, f"{where}.{name}", class_row, exact=exact)
        if any(row[key] is None for row in rows) or len(rows) != len({row["class"] for row in rows}): _error(f"{where}.{name} is not canonical")
    classes = _rows(item["classes"], fields, f"{where}.classes", class_row, exact=exact)
    if classes != sorted(classes, key=lambda row: row["class"]) or len(classes) != len({row["class"] for row in classes}): _error(f"{where}.classes is not canonical")
    if item["classes_analyzed"] != len(classes): _error(f"{where}.classes_analyzed does not match classes")
    if expected_population is not None and item["classes_analyzed"] != expected_population: _error(f"{where}.classes_analyzed does not match size.classes")
    for name, key in rankings.items():
        eligible = [row for row in classes if row[key] is not None]
        expected = sorted(eligible, key=lambda row: (-row[key], row["class"]))[:10]
        actual_rows = [{field: row[field] for field in fields} for row in item[name]]
        expected_rows = [{field: row[field] for field in fields} for row in expected]
        if not _typed_tree_equal(actual_rows, expected_rows): _error(f"{where}.{name} is not an exact class ranking")


def _validate_call_graph(value: Any, where: str) -> None:
    item = _obj(value, set(CALL_GRAPH), where, exact=False)
    for key in CALL_OVERVIEW:
        (_number(item[key], f"{where}.{key}", rate=key.endswith("_rate")) if key.endswith("_rate") else _count(item[key], f"{where}.{key}"))
    for key in ("entrypoints", "leaf_callables", "isolated_callables", "longest_call_chain", "deepest_nested_call_owners"): _sorted_strings(item[key], f"{where}.{key}") if key != "longest_call_chain" else None
    if not isinstance(item["longest_call_chain"], list) or any(not isinstance(value, str) for value in item["longest_call_chain"]): _error(f"{where}.longest_call_chain must contain strings")
    _sorted_groups(item["recursive_components"], f"{where}.recursive_components")
    def edge(row: Mapping[str, Any], place: str) -> None:
        _string(row["caller"], f"{place}.caller"); _string(row["target"], f"{place}.target"); _count(row["callsites"], f"{place}.callsites")
    edges = _rows(item["heaviest_edges"], {"caller", "target", "callsites"}, f"{where}.heaviest_edges", edge)
    if edges != sorted(edges, key=lambda row: (-row["callsites"], row["caller"], row["target"])) or len(edges) != len({(row["caller"], row["target"]) for row in edges}): _error(f"{where}.heaviest_edges is not canonical")
    for name, count_key in (("highest_fan_in", "degree"), ("highest_fan_out", "degree"), ("maximum_transitive_reach", "reachable_nodes")):
        peak = _obj(item[name], {count_key, "nodes"}, f"{where}.{name}", exact=False); _count(peak[count_key], f"{where}.{name}.{count_key}"); _sorted_strings(peak["nodes"], f"{where}.{name}.nodes")
    def score(row: Mapping[str, Any], place: str) -> None: _string(row["node"], f"{place}.node"); _number(row["score"], f"{place}.score")
    for name in ("pagerank_top", "betweenness_top"):
        rows = _rows(item[name], {"node", "score"}, f"{where}.{name}", score)
        if rows != sorted(rows, key=lambda row: (-row["score"], row["node"])) or len(rows) != len({row["node"] for row in rows}): _error(f"{where}.{name} is not canonical")
    def risk(row: Mapping[str, Any], place: str) -> None:
        score(row, place)
        for key in ("cyclomatic", "cognitive", "fan_in", "transitive_reach"): _count(row[key], f"{place}.{key}")
        _number(row["betweenness"], f"{place}.betweenness")
    risks = _rows(item["risk_top"], {"node", "score", "cyclomatic", "cognitive", "fan_in", "betweenness", "transitive_reach"}, f"{where}.risk_top", risk)
    if risks != sorted(risks, key=lambda row: (-row["score"], row["node"])) or len(risks) != len({row["node"] for row in risks}): _error(f"{where}.risk_top is not canonical")
    _string_count_map(item["node_kinds"], f"{where}.node_kinds")


def validate_metrics_source_v1(source: Mapping[str, Any]) -> None:
    root = _obj(source, {"schema_version", "metrics_semantics_version", "input", "metrics"}, "source", exact=False)
    if type(root["schema_version"]) is not int or root["schema_version"] != 1 or type(root["metrics_semantics_version"]) is not int or root["metrics_semantics_version"] != 4: _error("unsupported Metrics DTO version")
    input_ = _obj(root["input"], {"graph_schema_version", "graph_fingerprint"}, "source.input", exact=False)
    if type(input_["graph_schema_version"]) is not int or input_["graph_schema_version"] != 1 or not isinstance(input_["graph_fingerprint"], str) or not _HEX.fullmatch(input_["graph_fingerprint"]): _error("invalid source graph identity")
    metrics = _obj(root["metrics"], {"size", "activity", "dependency_graph", "architecture", "code_quality", "object_oriented", "call_graph"}, "source.metrics", exact=False)
    size = _obj(metrics["size"], set(SIZE), "source.metrics.size", exact=False)
    for key in SIZE: _count(size[key], f"source.metrics.size.{key}")
    activity = _obj(metrics["activity"], set(ACTIVITY), "source.metrics.activity", exact=False)
    for key in ACTIVITY[:3]: _count(activity[key], f"source.metrics.activity.{key}")
    for key in ACTIVITY[3:]: _number(activity[key], f"source.metrics.activity.{key}")
    _validate_dependency(metrics["dependency_graph"], "source.metrics.dependency_graph", exact=False, details=True)
    _validate_architecture(metrics["architecture"], "source.metrics.architecture", exact=False)
    _validate_quality(metrics["code_quality"], "source.metrics.code_quality", expected_population=size["functions"] + size["methods"])
    _validate_object_oriented(metrics["object_oriented"], "source.metrics.object_oriented",
                              expected_population=size["classes"])
    _validate_call_graph(metrics["call_graph"], "source.metrics.call_graph")


def metrics_view_fingerprint(view: Mapping[str, Any]) -> str:
    if not isinstance(view, Mapping): _error("root must be an object")
    content = {key: value for key, value in view.items() if key != "view_fingerprint"}
    return hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def validate_metrics_view_v1(view: Mapping[str, Any], *, verify_fingerprint: bool = True) -> None:
    root = _obj(view, _ROOT, "root")
    if root["artifact_kind"] != "metrics_view" or type(root["view_schema_version"]) is not int or root["view_schema_version"] != 1: _error("invalid envelope identity")
    profile = _obj(root["profile"], {"id", "version"}, "profile"); expected = metrics_profile_metadata(profile["id"], profile["version"])
    source = _obj(root["source"], {"metrics_schema_version", "metrics_semantics_version", "graph_schema_version", "graph_fingerprint"}, "source")
    if any(type(source[key]) is not int for key in ("metrics_schema_version", "metrics_semantics_version", "graph_schema_version")) or (source["metrics_schema_version"], source["metrics_semantics_version"], source["graph_schema_version"]) != (1, 4, 1) or not isinstance(source["graph_fingerprint"], str) or not _HEX.fullmatch(source["graph_fingerprint"]): _error("invalid source identity")
    completeness = _obj(root["completeness"], {"kind", "preserves", "omits"}, "completeness")
    if not _typed_tree_equal(completeness, expected): _error("completeness does not match registry")
    payload = root["payload"]
    if profile["id"] == "metrics.overview":
        payload = _obj(payload, {"metrics", "population_metadata"}, "payload"); metrics = _obj(payload["metrics"], {"size", "activity", "dependency_graph", "code_quality", "object_oriented", "call_graph"}, "payload.metrics")
        size = _obj(metrics["size"], set(SIZE), "payload.metrics.size"); [ _count(size[k], f"size.{k}") for k in SIZE ]
        activity = _obj(metrics["activity"], set(ACTIVITY), "payload.metrics.activity"); [ _count(activity[k], f"activity.{k}") for k in ACTIVITY[:3] ]; [ _number(activity[k], f"activity.{k}") for k in ACTIVITY[3:] ]
        _validate_dependency(metrics["dependency_graph"], "payload.metrics.dependency_graph", exact=True, details=False)
        _count(_obj(metrics["code_quality"], {"analyzed_callables"}, "code_quality")["analyzed_callables"], "analyzed_callables"); _count(_obj(metrics["object_oriented"], {"classes_analyzed"}, "object_oriented")["classes_analyzed"], "classes_analyzed")
        calls = _obj(metrics["call_graph"], set(CALL_OVERVIEW), "call_graph"); [(_number(calls[k], k, rate=k.endswith("_rate")) if k.endswith("_rate") else _count(calls[k], k)) for k in CALL_OVERVIEW]
    elif profile["id"] == "metrics.architecture":
        payload = _obj(payload, {"metrics", "population_metadata", "package_grouping"}, "payload"); metrics = _obj(payload["metrics"], {"activity", "dependency_graph", "architecture"}, "payload.metrics")
        activity = _obj(metrics["activity"], {"local_imports", "external_imports"}, "activity"); _count(activity["local_imports"], "local_imports"); _count(activity["external_imports"], "external_imports")
        _validate_dependency(metrics["dependency_graph"], "dependency_graph", exact=True, details=True); _validate_architecture(metrics["architecture"], "architecture", exact=True)
        if not _typed_tree_equal(payload["package_grouping"], PACKAGE_GROUPING): _error("package_grouping does not match static contract")
    elif profile["id"] == "metrics.quality":
        payload = _obj(payload, {"metrics", "population_metadata", "threshold_policy", "truncation_metadata"}, "payload")
        metrics = _obj(payload["metrics"], {"size", "code_quality"}, "payload.metrics")
        size = _obj(metrics["size"], {"functions", "methods"}, "payload.metrics.size")
        _count(size["functions"], "size.functions"); _count(size["methods"], "size.methods")
        _validate_quality(metrics["code_quality"], "payload.metrics.code_quality", exact=True, expected_population=size["functions"] + size["methods"])
        if not _typed_tree_equal(payload["threshold_policy"], THRESHOLD_POLICY): _error("threshold_policy does not match static contract")
        truncation = _obj(payload["truncation_metadata"], {"descriptor_version", "rankings"}, "payload.truncation_metadata")
        ranking = _obj(truncation["rankings"], {"metrics.code_quality.largest_callables"}, "payload.truncation_metadata.rankings")
        descriptor = _obj(ranking["metrics.code_quality.largest_callables"], {"limit", "returned_count", "total_matching", "truncated", "ordering"}, "truncation descriptor")
        returned = len(metrics["code_quality"]["largest_callables"]); total = metrics["code_quality"]["analyzed_callables"]
        expected_descriptor = {"limit": 10, "returned_count": returned, "total_matching": total,
                               "truncated": total > returned,
                               "ordering": ["lines descending", "node ascending"]}
        expected_truncation = {"descriptor_version": 1, "rankings": {
            "metrics.code_quality.largest_callables": expected_descriptor,
        }}
        if not _typed_tree_equal(truncation, expected_truncation): _error("truncation_metadata is inconsistent")
    elif profile["id"] == "metrics.objects":
        payload = _obj(payload, {"metrics", "population_metadata", "topology_policy",
                                 "interpretation_policy", "truncation_metadata"}, "payload")
        metrics = _obj(payload["metrics"], {"size", "object_oriented"}, "payload.metrics")
        size = _obj(metrics["size"], {"classes", "methods", "fields"}, "payload.metrics.size")
        for key in ("classes", "methods", "fields"): _count(size[key], f"payload.metrics.size.{key}")
        objects = metrics["object_oriented"]
        _validate_object_oriented(objects, "payload.metrics.object_oriented", exact=True,
                                  expected_population=size["classes"])
        if not _typed_tree_equal(payload["topology_policy"], OBJECT_TOPOLOGY_POLICY): _error("topology_policy does not match static contract")
        if not _typed_tree_equal(payload["interpretation_policy"], OBJECT_INTERPRETATION_POLICY): _error("interpretation_policy does not match static contract")
        names = {
            "highest_weighted_method_complexity": ("wmc", "wmc descending", objects["classes_analyzed"]),
            "highest_class_coupling": ("cbo", "cbo descending", objects["classes_analyzed"]),
            "largest_response_sets": ("rfc", "rfc descending", objects["classes_analyzed"]),
            "lowest_cohesion": ("lcom", "lcom descending", sum(row["lcom"] is not None for row in objects["classes"])),
            "deepest_inheritance": ("dit", "dit descending", sum(row["dit"] is not None for row in objects["classes"])),
            "most_direct_children": ("noc", "noc descending", objects["classes_analyzed"]),
        }
        expected_rankings = {}
        for name, (_, ordering, total) in names.items():
            returned = len(objects[name])
            expected_rankings[f"metrics.object_oriented.{name}"] = {
                "limit": 10, "returned_count": returned, "total_matching": total,
                "truncated": total > returned, "ordering": [ordering, "class ascending"],
            }
        expected_truncation = {"descriptor_version": 1, "rankings": expected_rankings}
        if not _typed_tree_equal(payload["truncation_metadata"], expected_truncation): _error("truncation_metadata is inconsistent")
    else:
        _error("unsupported metrics profile dispatch")
    if not _typed_tree_equal(payload["population_metadata"], population_metadata(profile["id"])): _error("population_metadata does not match static contract")
    fingerprint = root["view_fingerprint"]
    if not isinstance(fingerprint, str) or not _HEX.fullmatch(fingerprint) or verify_fingerprint and fingerprint != metrics_view_fingerprint(root): _error("invalid view_fingerprint")


def serialize_metrics_view(view: Mapping[str, Any]) -> bytes:
    validate_metrics_view_v1(view)
    return (json.dumps(view, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


__all__ = ["OBJECT_INTERPRETATION_POLICY", "OBJECT_TOPOLOGY_POLICY", "PACKAGE_GROUPING",
           "THRESHOLD_POLICY", "metrics_view_fingerprint", "population_metadata",
           "serialize_metrics_view", "validate_metrics_source_v1", "validate_metrics_view_v1"]
