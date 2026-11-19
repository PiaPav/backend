"""Thin adapters to canonical metrics and Graph DTO public APIs."""

import json
from pathlib import Path

import graph_dto
import metrics
import views

from metrics_service.application.errors import InvalidGraphDtoError, InvalidMetricsDtoError


_INVALID_GRAPH_MESSAGE = "Canonical graph validation failed"
_INVALID_METRICS_MESSAGE = "Canonical metrics validation failed"


class CanonicalMetricsGateway:
    def calculate(self, graph_path: Path, output_path: Path) -> Path:
        return metrics.calculate_metrics(graph_path, output_path)


class CanonicalArtifactValidator:
    def validate_graph(self, graph_path: Path) -> str:
        try:
            graph = json.loads(graph_path.read_bytes().decode("utf-8"))
            graph_dto.validate_graph_v1(graph)
            if graph.get("schema_version") != 1 or graph.get("parser_semantics_version") != 7:
                raise ValueError("unsupported canonical graph version")
            return graph_dto.graph_fingerprint(graph)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError, KeyError) as error:
            raise InvalidGraphDtoError(_INVALID_GRAPH_MESSAGE) from error

    def validate_metrics(self, metrics_path: Path, graph_fingerprint: str) -> None:
        try:
            value = json.loads(metrics_path.read_bytes().decode("utf-8"))
            views.validate_metrics_source_v1(value)
            linkage = value["input"]
            if (set(linkage) != {"graph_schema_version", "graph_fingerprint"}
                    or linkage["graph_schema_version"] != 1
                    or linkage["graph_fingerprint"] != graph_fingerprint):
                raise ValueError("Metrics DTO input linkage mismatch")
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError, KeyError) as error:
            raise InvalidMetricsDtoError(_INVALID_METRICS_MESSAGE) from error


__all__ = ["CanonicalArtifactValidator", "CanonicalMetricsGateway"]
