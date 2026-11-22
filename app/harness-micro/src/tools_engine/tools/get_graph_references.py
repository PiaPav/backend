import copy

from response_models.models import ToolName
from rules.rules_config import RULES_CONFIG
from tools_engine.accessors.graph import GraphAccessor
from tools_engine.interface.tool import AbstractTool, InvalidArtifact, InvalidToolArguments, NodeNotFound
from tools_engine.models.tool_result import Completeness, ToolOutput


class GetGraphReferences(AbstractTool):
    name = ToolName.Get_Graph_References

    def execute(self, analysis_context, **kwargs):
        owner = kwargs["OWNER-NODE-ID"]
        ref_type, status = kwargs.get("REFERENCE-TYPE"), kwargs.get("STATUS")
        if (not isinstance(owner, str) or not owner
                or ref_type is not None and ref_type not in {"call", "import", "type"}
                or status is not None and status not in {"exact", "ambiguous", "external", "dynamic", "unresolved"}):
            raise InvalidToolArguments()
        limit = RULES_CONFIG.max_graph_references_limit
        if type(limit) is not int or limit <= 0 or limit > 1000:
            raise InvalidArtifact(details={"artifact": "rules_config"})
        accessor = GraphAccessor(analysis_context)
        if owner not in accessor.prepared().by_id:
            raise NodeNotFound(details={"node_id": owner})
        collections = accessor.references()
        owner_fields = {"call": "caller_id", "import": "importer_id", "type": "owner_id"}
        matches = []
        totals = {kind: 0 for kind in owner_fields}
        for kind in ("call", "import", "type"):
            if ref_type is not None and kind != ref_type:
                continue
            for ref in collections[kind]:
                if ref[owner_fields[kind]] == owner and (status is None or ref["resolution"] == status):
                    totals[kind] += 1
                    matches.append((kind, ref))
        matches.sort(key=lambda item: (("call", "import", "type").index(item[0]), item[1]["id"]))
        selected = matches[:limit]
        returned_counts = {kind: 0 for kind in owner_fields}
        references = []
        for kind, ref in selected:
            returned_counts[kind] += 1
            references.append({"reference_type": kind, "owner_id": owner, "reference": copy.deepcopy(ref)})
        total, returned = len(matches), len(selected)
        return ToolOutput({
            "owner_node_id": owner, "reference_type": ref_type, "status": status,
            "references": references,
            "counts": {kind: {"total": totals[kind], "returned": returned_counts[kind]}
                       for kind in owner_fields},
        }, profile_id="canonical.full",
            completeness=Completeness(returned < total, total, returned))
