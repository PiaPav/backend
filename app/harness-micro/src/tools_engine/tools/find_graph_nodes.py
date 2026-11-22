import copy

from response_models.models import ToolName
from rules.rules_config import RULES_CONFIG
from tools_engine.accessors.graph import GraphAccessor, valid_graph_path
from tools_engine.interface.tool import AbstractTool, InvalidArtifact, InvalidToolArguments
from tools_engine.models.analysis_context import AnalysisContext
from tools_engine.models.tool_result import Completeness, ToolOutput


class FindGraphNodes(AbstractTool):
    name = ToolName.Find_Graph_Nodes

    def execute(self, analysis_context: AnalysisContext, **kwargs):
        query = kwargs["QUERY"]
        if not query:
            raise InvalidToolArguments("QUERY не должен быть пустым")
        path = kwargs.get("PATH")
        if path is not None and not valid_graph_path(path):
            raise InvalidToolArguments("PATH должен быть относительным POSIX-путём")
        default = RULES_CONFIG.default_graph_search_limit
        maximum = RULES_CONFIG.max_graph_search_limit
        if (type(default) is not int or default <= 0 or type(maximum) is not int
                or maximum <= 0 or default > maximum):
            raise InvalidArtifact(details={"artifact": "rules_config"})
        limit = kwargs.get("LIMIT", default)
        if type(limit) is not int or limit < 1 or limit > maximum:
            raise InvalidToolArguments("LIMIT выходит за настроенный диапазон", {"maximum": maximum})
        folded = query.casefold()
        matches = [node for node in GraphAccessor(analysis_context).prepared().searchable
                   if folded in node["qualified_name"].casefold()
                   and (kwargs.get("KIND") is None or node["kind"] == kwargs["KIND"])
                   and (path is None or node["path"] == path)]
        selected = matches[:limit]
        projections = [{key: copy.deepcopy(node[key]) for key in
                        ("id", "kind", "qualified_name", "path", "location")}
                       for node in selected]
        return ToolOutput(
            {"nodes": projections}, profile_id=GraphAccessor.PROFILE_ID,
            completeness=Completeness(len(selected) < len(matches), len(matches), len(selected)),
        )
