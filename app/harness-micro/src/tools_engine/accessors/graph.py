import copy
import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from tools_engine.interface.tool import InvalidArtifact, ProfileNotFound
from tools_engine.models.analysis_context import AnalysisContext


KINDS = ("file", "class", "field", "method", "function", "constant")


def valid_graph_path(value: object) -> bool:
    if not isinstance(value, str) or not value or "\\" in value or value.startswith("/"):
        return False
    parts = value.split("/")
    return ":" not in parts[0] and all(part not in ("", ".", "..") for part in parts)


@dataclass(frozen=True, slots=True)
class PreparedGraph:
    by_id: Mapping[str, dict[str, Any]]
    searchable: tuple[dict[str, Any], ...]


class GraphAccessor:
    PROFILE_ID = "canonical.full"
    CACHE_KEY = "graph:canonical.full:v1"

    def __init__(self, context: AnalysisContext):
        self.context = context

    def prepared(self) -> PreparedGraph:
        return self.context.get_or_create_cached(self.CACHE_KEY, self._load)

    def _load(self) -> PreparedGraph:
        path = self.context.graph_profiles.get(self.PROFILE_ID)
        if path is None:
            raise ProfileNotFound(details={"profile_id": self.PROFILE_ID})
        try:
            value = json.loads(Path(path).read_text(encoding="utf-8"))
            nodes = self._validate_root(value)
            by_id: dict[str, dict[str, Any]] = {}
            for node in nodes:
                self._validate_node(node)
                if node["id"] in by_id:
                    raise ValueError
                by_id[node["id"]] = node
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
            raise InvalidArtifact(details={
                "artifact": "graph_profile", "profile_id": self.PROFILE_ID,
            }) from None
        searchable = tuple(sorted(nodes, key=lambda node: (
            node["qualified_name"].casefold(), node["qualified_name"], node["id"]
        )))
        return PreparedGraph(MappingProxyType(by_id), searchable)

    @staticmethod
    def _validate_root(value: Any) -> list[dict[str, Any]]:
        if (not isinstance(value, dict)
                or type(value.get("schema_version")) is not int
                or value["schema_version"] != 1
                or not isinstance(value.get("nodes"), list)):
            raise ValueError
        return value["nodes"]

    @staticmethod
    def _validate_node(node: Any) -> None:
        if not isinstance(node, dict):
            raise ValueError
        for field in ("id", "kind", "qualified_name", "path"):
            if not isinstance(node.get(field), str) or not node[field]:
                raise ValueError
        if node["kind"] not in KINDS or not valid_graph_path(node["path"]):
            raise ValueError
        location = node.get("location")
        if not isinstance(location, dict) or location.get("path") != node["path"]:
            raise ValueError
        if type(location.get("line")) is not int or location["line"] <= 0:
            raise ValueError
        if type(location.get("column")) is not int or location["column"] < 0:
            raise ValueError

    @staticmethod
    def copy_node(node: dict[str, Any]) -> dict[str, Any]:
        return copy.deepcopy(node)
