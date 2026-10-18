"""Aggregate callable complexity, async and exception-flow metrics."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Any
from .identity import graph_files, legacy_file_id
from .complexity import canonical_callable_metrics
from .projections import MetricsGraphProjection


def callable_metrics(
    graph: Mapping[str, Any], *, projection: MetricsGraphProjection | None = None
) -> dict[str, dict[str, Any]]:
    if graph.get("parser_semantics_version") in {3, 4}:
        return canonical_callable_metrics(graph)
    result: dict[str, dict[str, Any]] = {}
    files = [file.data for file in projection.legacy_files] if projection else graph_files(graph)
    for file in files:
        module = legacy_file_id(file)
        for function in file.get("functions", []):
            if isinstance(function, Mapping) and isinstance(function.get("metrics"), Mapping):
                result[f"{module}.{function.get('name')}"] = dict(function["metrics"])
        for class_info in file.get("classes", []):
            if not isinstance(class_info, Mapping):
                continue
            for method in class_info.get("methods", []):
                if isinstance(method, Mapping) and isinstance(method.get("metrics"), Mapping):
                    name = f"{module}.{class_info.get('name')}.{method.get('name')}"
                    result[name] = dict(method["metrics"])
    return result


def _average(items: list[float]) -> float:
    return round(sum(items) / len(items), 4) if items else 0.0


def calculate_quality_metrics(
    graph: Mapping[str, Any], *, projection: MetricsGraphProjection | None = None
) -> dict[str, Any]:
    metrics = callable_metrics(graph, projection=projection)
    raised: Counter[str] = Counter()
    caught: Counter[str] = Counter()
    broad_handlers: list[dict[str, Any]] = []
    for name, item in metrics.items():
        raised.update(map(str, item.get("raised_exceptions", [])))
        caught.update(map(str, item.get("caught_exceptions", [])))
        if item.get("broad_exception_handlers", 0):
            broad_handlers.append(
                {"node": name, "count": int(item["broad_exception_handlers"])}
            )

    ranked = sorted(
        metrics.items(),
        key=lambda pair: (
            -int(pair[1].get("cyclomatic_complexity", 1)),
            -int(pair[1].get("cognitive_complexity", 0)),
            pair[0],
        ),
    )
    high_complexity = [
        {
            "node": name,
            "cyclomatic": int(item.get("cyclomatic_complexity", 1)),
            "cognitive": int(item.get("cognitive_complexity", 0)),
            "lines": int(item.get("lines_of_code", 1)),
            "nesting": int(item.get("max_nesting", 0)),
        }
        for name, item in ranked
        if int(item.get("cyclomatic_complexity", 1)) >= 10
        or int(item.get("cognitive_complexity", 0)) >= 15
    ]
    largest = sorted(
        (
            {"node": name, "lines": int(item.get("lines_of_code", 1))}
            for name, item in metrics.items()
        ),
        key=lambda item: (-item["lines"], item["node"]),
    )[:10]

    async_nodes = [name for name, item in metrics.items() if item.get("is_async")]
    return {
        "analyzed_callables": len(metrics),
        "average_cyclomatic_complexity": _average(
            [float(item.get("cyclomatic_complexity", 1)) for item in metrics.values()]
        ),
        "average_cognitive_complexity": _average(
            [float(item.get("cognitive_complexity", 0)) for item in metrics.values()]
        ),
        "average_lines_per_callable": _average(
            [float(item.get("lines_of_code", 1)) for item in metrics.values()]
        ),
        "maximum_control_nesting": max(
            (int(item.get("max_nesting", 0)) for item in metrics.values()), default=0
        ),
        "high_complexity_callables": high_complexity,
        "largest_callables": largest,
        "deeply_nested_callables": sorted(
            [
                {
                    "node": name,
                    "nesting": int(item.get("max_nesting", 0)),
                }
                for name, item in metrics.items()
                if int(item.get("max_nesting", 0)) >= 4
            ],
            key=lambda item: (-item["nesting"], item["node"]),
        ),
        "async": {
            "functions": len(async_nodes),
            "without_await": sorted(
                name
                for name in async_nodes
                if int(metrics[name].get("await_count", 0)) == 0
            ),
        },
        "exceptions": {
            "raise_statements": sum(
                int(item.get("raise_count", 0)) for item in metrics.values()
            ),
            "callables_raising": sum(
                int(item.get("raise_count", 0)) > 0 for item in metrics.values()
            ),
            "raised_types": dict(sorted(raised.items())),
            "caught_types": dict(sorted(caught.items())),
            "broad_handlers": sorted(
                broad_handlers, key=lambda item: (-item["count"], item["node"])
            ),
        },
    }
