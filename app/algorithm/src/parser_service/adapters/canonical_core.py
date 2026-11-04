"""Thin adapters to canonical parser and Graph DTO public APIs."""

import json
from pathlib import Path

import graph_dto
import parser

from parser_service.application.errors import InvalidGraphDtoError


_INVALID_GRAPH_MESSAGE = "Canonical graph validation failed"


class CanonicalParserGateway:
    def parse(self, source_path: Path, output_path: Path) -> Path:
        return parser.parse_project(source_path, output_path)


class CanonicalGraphValidator:
    def validate(self, graph_path: Path) -> str:
        try:
            graph = json.loads(graph_path.read_bytes().decode("utf-8"))
            graph_dto.validate_graph_v1(graph)
            if graph.get("schema_version") != 1 or graph.get("parser_semantics_version") != 7:
                raise ValueError("unsupported canonical graph version")
            return graph_dto.graph_fingerprint(graph)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError, KeyError) as error:
            raise InvalidGraphDtoError(_INVALID_GRAPH_MESSAGE) from error


__all__ = ["CanonicalGraphValidator", "CanonicalParserGateway"]
