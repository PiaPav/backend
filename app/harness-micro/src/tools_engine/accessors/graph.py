import copy
import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from tools_engine.interface.tool import InvalidArtifact, ProfileNotFound
from tools_engine.models.analysis_context import AnalysisContext


KINDS = ("file", "module", "class", "field", "function", "method", "constant")
EDGE_KINDS = ("contains", "imports", "inherits", "field_type", "accesses_field", "calls", "awaits")
PROFILE_RELATIONS = {
    "canonical.full": frozenset(EDGE_KINDS),
    "structure.declarations": frozenset(("contains",)),
    "dependency.files": frozenset(("imports",)),
    "dependency.architecture": frozenset(("contains", "imports")),
    "calls.topology": frozenset(("contains", "calls", "awaits")),
    "calls.detailed": frozenset(("contains", "calls", "awaits")),
    "types.topology": frozenset(("contains", "inherits", "field_type")),
    "objects.metrics_basis": frozenset(("contains", "inherits", "field_type", "accesses_field", "calls", "awaits")),
}


def valid_graph_path(value: object) -> bool:
    if not isinstance(value, str) or not value or "\\" in value or value.startswith("/"):
        return False
    parts = value.split("/")
    return ":" not in parts[0] and all(part not in ("", ".", "..") for part in parts)


@dataclass(frozen=True, slots=True)
class PreparedGraph:
    by_id: Mapping[str, dict[str, Any]]
    searchable: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class GraphTopology:
    by_id: Mapping[str, dict[str, Any]]
    nodes: tuple[dict[str, Any], ...]
    edges: tuple[dict[str, Any], ...]


class GraphAccessor:
    PROFILE_ID = "canonical.full"
    CACHE_KEY = "graph:canonical.full:v1"

    def __init__(self, context: AnalysisContext):
        self.context = context

    def prepared(self) -> PreparedGraph:
        return self.context.get_or_create_cached(self.CACHE_KEY, self._load)

    def raw(self, profile_id: str) -> dict[str, Any]:
        if profile_id not in self.context.graph_profiles:
            raise ProfileNotFound(details={"profile_id": profile_id})
        value = self.context.get_or_create_cached(
            f"graph:raw:{profile_id}:v1", lambda: self._read(profile_id)
        )
        return copy.deepcopy(value)

    def topology(self, profile_id: str) -> GraphTopology:
        if profile_id not in PROFILE_RELATIONS:
            raise ProfileNotFound(details={"profile_id": profile_id})
        return self.context.get_or_create_cached(
            f"graph:topology:{profile_id}:v1", lambda: self._topology(profile_id)
        )

    def references(self) -> Mapping[str, tuple[dict[str, Any], ...]]:
        return self.context.get_or_create_cached("graph:references:canonical.full:v1", self._references)

    def _load(self) -> PreparedGraph:
        document = self.raw(self.PROFILE_ID)
        try:
            nodes = self._canonical_nodes(document)
            by_id = self._nodes(nodes, require_location=True)
        except (TypeError, ValueError):
            self._invalid(self.PROFILE_ID)
        searchable = tuple(sorted(nodes, key=lambda node: (
            node["qualified_name"].casefold(), node["qualified_name"], node["id"]
        )))
        return PreparedGraph(MappingProxyType(by_id), searchable)

    def _read(self, profile_id: str) -> dict[str, Any]:
        try:
            value = json.loads(Path(self.context.graph_profiles[profile_id]).read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError
            return value
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
            self._invalid(profile_id)

    def _topology(self, profile_id: str) -> GraphTopology:
        value = self.raw(profile_id)
        try:
            if profile_id == self.PROFILE_ID:
                nodes = self._canonical_nodes(value)
                edges = value.get("edges")
                require_location = True
            else:
                if (value.get("artifact_kind") != "graph_view"
                        or value.get("view_schema_version") != 1
                        or type(value.get("view_schema_version")) is not int
                        or not isinstance(value.get("profile"), dict)
                        or value["profile"].get("id") != profile_id
                        or value["profile"].get("version") != 1
                        or type(value["profile"].get("version")) is not int
                        or not isinstance(value.get("payload"), dict)):
                    raise ValueError
                nodes, edges = value["payload"].get("nodes"), value["payload"].get("edges")
                require_location = False
            if not isinstance(edges, list):
                raise ValueError
            by_id = self._nodes(nodes, require_location)
            edge_ids: set[str] = set()
            for edge in edges:
                if not isinstance(edge, dict) or any(not isinstance(edge.get(k), str) or not edge[k]
                                                     for k in ("id", "kind", "source_id", "target_id")):
                    raise ValueError
                if (edge["id"] in edge_ids or edge["kind"] not in PROFILE_RELATIONS[profile_id]
                        or edge["source_id"] not in by_id or edge["target_id"] not in by_id):
                    raise ValueError
                for field in ("weight", "exact_occurrence_count"):
                    if field in edge and (type(edge[field]) is not int or edge[field] <= 0):
                        raise ValueError
                edge_ids.add(edge["id"])
            return GraphTopology(MappingProxyType(by_id), tuple(nodes), tuple(edges))
        except (TypeError, ValueError):
            self._invalid(profile_id)

    def _references(self) -> Mapping[str, tuple[dict[str, Any], ...]]:
        value = self.raw(self.PROFILE_ID)
        try:
            by_id = self._nodes(self._canonical_nodes(value), True)
            semantics = value.get("parser_semantics_version")
            if type(semantics) is not int or not 1 <= semantics <= 7:
                raise ValueError
            specs = {
                "call": ("callsites", "caller_id", {"exact", "ambiguous", "external", "dynamic", "unresolved"}),
                "import": ("import_references", "importer_id", {"exact", "external", "unresolved"}),
                "type": ("type_references", "owner_id", {"exact", "ambiguous", "external", "unresolved"}),
            }
            result = {}
            for kind, (collection, owner_field, statuses) in specs.items():
                optional = (semantics == 1 and collection in {"type_references", "import_references"}
                            or semantics in {2, 3} and collection == "import_references")
                records = value.get(collection, [] if optional else None)
                if not isinstance(records, list):
                    raise ValueError
                seen = set()
                for ref in records:
                    if (not isinstance(ref, dict) or not isinstance(ref.get("id"), str) or not ref["id"]
                            or ref["id"] in seen or ref.get(owner_field) not in by_id
                            or ref.get("resolution") not in statuses):
                        raise ValueError
                    seen.add(ref["id"])
                    owner_kind = by_id[ref[owner_field]]["kind"]
                    if (kind == "call" and owner_kind not in {"file", "module", "function", "method"}
                            or kind == "import" and owner_kind not in {"file", "module"}):
                        raise ValueError
                    self._validate_reference(ref, kind, by_id)
                result[kind] = tuple(records)
            return MappingProxyType(result)
        except (TypeError, ValueError):
            self._invalid(self.PROFILE_ID)

    @staticmethod
    def _validate_reference(ref, kind, nodes):
        required = {
            "call": {"expression", "syntactic_depth", "awaited", "location"},
            "import": {"kind", "module", "name", "alias", "level", "location", "target_id", "candidate_ids"},
            "type": {"role", "expression", "location"},
        }[kind]
        if not required.issubset(ref):
            raise ValueError
        target, candidates, status = ref.get("target_id"), ref.get("candidate_ids", []), ref["resolution"]
        if (not isinstance(candidates, list) or candidates != sorted(candidates)
                or len(candidates) != len(set(candidates)) or any(x not in nodes for x in candidates)):
            raise ValueError
        if status == "exact":
            if target not in nodes or candidates:
                raise ValueError
        elif target is not None:
            raise ValueError
        if status == "ambiguous" and len(candidates) < 2 or status != "ambiguous" and candidates:
            raise ValueError
        allowed = {"call": {"function", "method"}, "type": {"class"}}.get(kind)
        if allowed and any(nodes[x]["kind"] not in allowed for x in candidates + ([target] if target else [])):
            raise ValueError
        if kind == "import" and target is not None and nodes[target]["kind"] not in {"file", "module"}:
            raise ValueError
        if kind == "call":
            if (not isinstance(ref.get("expression"), str) or not ref["expression"]
                    or type(ref.get("syntactic_depth")) is not int
                    or ref["syntactic_depth"] < 0 or type(ref.get("awaited")) is not bool):
                raise ValueError
        elif kind == "import":
            if (ref.get("kind") not in {"import", "from"}
                    or not isinstance(ref.get("module"), str)
                    or not isinstance(ref.get("name"), str) or not ref["name"]
                    or ref.get("alias") is not None
                    and (not isinstance(ref["alias"], str) or not ref["alias"])
                    or type(ref.get("level")) is not int or ref["level"] < 0
                    or candidates != []):
                raise ValueError
            if (ref["kind"] == "import"
                    and (ref["module"] != "" or ref["level"] != 0 or ref["name"] == "*")
                    or ref["kind"] == "from" and ref["level"] == 0 and not ref["module"]
                    or status == "external" and ref["level"] != 0
                    or status == "unresolved" and ref["level"] <= 0):
                raise ValueError
        else:
            role = ref.get("role")
            if (role not in {"base", "field_type"}
                    or not isinstance(ref.get("expression"), str) or not ref["expression"]
                    or nodes[ref["owner_id"]]["kind"] != ("class" if role == "base" else "field")):
                raise ValueError
        location = ref.get("location")
        if (not isinstance(location, dict) or not valid_graph_path(location.get("path"))
                or type(location.get("line")) is not int or location["line"] <= 0
                or type(location.get("column")) is not int or location["column"] < 0):
            raise ValueError
        if kind == "import" and location["path"] != nodes[ref["importer_id"]]["path"]:
            raise ValueError

    @staticmethod
    def _canonical_nodes(value):
        if type(value.get("schema_version")) is not int or value["schema_version"] != 1 or not isinstance(value.get("nodes"), list):
            raise ValueError
        return value["nodes"]

    @classmethod
    def _nodes(cls, nodes, require_location):
        if not isinstance(nodes, list):
            raise ValueError
        result = {}
        for node in nodes:
            cls._validate_node(node, require_location)
            if node["id"] in result:
                raise ValueError
            result[node["id"]] = node
        return result

    @staticmethod
    def _validate_node(node: Any, require_location: bool = True) -> None:
        if not isinstance(node, dict):
            raise ValueError
        for field in ("id", "kind", "path"):
            if not isinstance(node.get(field), str) or not node[field]:
                raise ValueError
        if not isinstance(node.get("qualified_name"), str):
            raise ValueError
        if node["kind"] not in KINDS or not valid_graph_path(node["path"]):
            raise ValueError
        location = node.get("location")
        if not require_location and location is None:
            return
        if not isinstance(location, dict) or location.get("path") != node["path"]:
            raise ValueError
        if type(location.get("line")) is not int or location["line"] <= 0:
            raise ValueError
        if type(location.get("column")) is not int or location["column"] < 0:
            raise ValueError

    @staticmethod
    def _invalid(profile_id):
        raise InvalidArtifact(details={"artifact": "graph_profile", "profile_id": profile_id}) from None

    @staticmethod
    def copy_node(node: dict[str, Any]) -> dict[str, Any]:
        return copy.deepcopy(node)
