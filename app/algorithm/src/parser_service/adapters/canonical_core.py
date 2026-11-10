"""Thin adapters to canonical parser and Graph DTO public APIs."""

import json
from pathlib import Path

import graph_dto
import parser

from parser_service.application.errors import InvalidGraphDtoError, InvalidSourceIndexError


_INVALID_GRAPH_MESSAGE = "Canonical graph validation failed"
_INVALID_SOURCE_INDEX_MESSAGE = "Canonical source index validation failed"


class CanonicalParserGateway:
    def parse(
        self, source_path: Path, graph_output_path: Path, source_index_output_path: Path
    ) -> tuple[Path, Path]:
        return parser.parse_project_with_source_index(
            source_path, graph_output_path, source_index_output_path
        )


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

    def validate_source_index(self, source_index_path: Path) -> str:
        try:
            value = json.loads(source_index_path.read_bytes().decode("utf-8"))
            if type(value) is not dict or set(value) != {
                "schema_version", "project", "files_by_name", "files", "symbols", "lookup"
            }:
                raise ValueError("invalid source index envelope")
            if value["schema_version"] != 1 or type(value["schema_version"]) is not int:
                raise ValueError("unsupported source index schema")
            project = value["project"]
            if type(project) is not dict or set(project) != {"root", "fingerprint", "file_count"}:
                raise ValueError("invalid source index project")
            fingerprint = project["fingerprint"]
            if (type(fingerprint) is not str or len(fingerprint) != 64
                    or any(character not in "0123456789abcdef" for character in fingerprint)):
                raise ValueError("invalid source index fingerprint")
            if type(project["root"]) is not str or not project["root"]:
                raise ValueError("invalid source index root")
            if type(project["file_count"]) is not int or project["file_count"] < 0:
                raise ValueError("invalid source index file count")
            for field in ("files_by_name", "files", "symbols", "lookup"):
                if type(value[field]) is not dict:
                    raise ValueError(f"invalid source index {field}")
            if project["file_count"] != len(value["files"]):
                raise ValueError("source index file count mismatch")
            return fingerprint
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError, KeyError) as error:
            raise InvalidSourceIndexError(_INVALID_SOURCE_INDEX_MESSAGE) from error


__all__ = ["CanonicalGraphValidator", "CanonicalParserGateway"]
