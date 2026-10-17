"""Pure complexity formulas over canonical Graph DTO facts."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def metrics_from_facts(facts: Mapping[str, Any]) -> dict[str, Any]:
    cyclomatic, cognitive, maximum = 1, 0, 0
    depths: list[int] = []
    controls = facts.get("controls", [])
    for control in controls:
        parent = control.get("parent_index")
        depth = depths[parent] + 1 if parent is not None else 0
        depths.append(depth)
        kind = control["kind"]
        if kind in {"try", "try_star"}: increment = 0
        elif kind == "match": increment = max(1, int(control["case_count"]) - 1)
        elif kind == "boolean": increment = max(0, int(control["operand_count"]) - 1)
        elif kind == "comprehension": increment = 1 + int(control["filter_count"])
        else: increment = 1
        cyclomatic += increment
        if kind == "boolean": cognitive += increment
        elif kind == "comprehension": cognitive += increment + depth
        else: cognitive += 1 + depth
        if kind not in {"boolean", "exception_handler"}:
            maximum = max(maximum, depth + 1)

    occurrences = facts.get("occurrences", [])
    caught = {item["expression"] for item in controls if item["kind"] == "exception_handler"}
    raised = {item["expression"] for item in occurrences if item["kind"] == "raise" and "expression" in item}
    attributes = {item["expression"] for item in occurrences if item["kind"] == "self_attribute"}
    span = facts["span"]
    return {
        "cyclomatic_complexity": cyclomatic,
        "cognitive_complexity": cognitive,
        "max_nesting": maximum,
        "lines_of_code": max(1, int(span["end"]["line"]) - int(span["start"]["line"]) + 1),
        "statement_count": sum(item["kind"] == "statement" for item in occurrences),
        "return_count": sum(item["kind"] == "return" for item in occurrences),
        "raise_count": sum(item["kind"] == "raise" for item in occurrences),
        "await_count": sum(item["kind"] == "await" for item in occurrences),
        "broad_exception_handlers": sum(
            item["kind"] == "exception_handler"
            and item["expression"] in {"bare except", "Exception", "BaseException"}
            for item in controls
        ),
        "raised_exceptions": sorted(raised),
        "caught_exceptions": sorted(caught),
        "self_attribute_accesses": sorted(attributes),
        "is_async": facts["is_async"],
    }


def canonical_callable_metrics(graph: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Return metrics keyed exclusively by stable callable node ID."""
    return {
        str(node["id"]): metrics_from_facts(node["complexity_facts"])
        for node in graph.get("nodes", [])
        if isinstance(node, Mapping)
        and node.get("kind") in {"function", "method"}
        and node.get("synthetic") is not True
        and isinstance(node.get("complexity_facts"), Mapping)
    }
