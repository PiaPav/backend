from response_models.models import ToolName
from tools_engine.accessors.graph import GraphAccessor
from tools_engine.interface.tool import AbstractTool, InvalidToolArguments, NodeNotFound
from tools_engine.models.analysis_context import AnalysisContext
from tools_engine.models.tool_result import ToolOutput


class GetGraphNode(AbstractTool):
    name = ToolName.Get_Graph_Node

    def execute(self, analysis_context: AnalysisContext, **kwargs):
        node_id = kwargs["NODE-ID"]
        if not node_id:
            raise InvalidToolArguments("NODE-ID не должен быть пустым")
        node = GraphAccessor(analysis_context).prepared().by_id.get(node_id)
        if node is None:
            raise NodeNotFound(details={"node_id": node_id})
        return ToolOutput(GraphAccessor.copy_node(node), profile_id=GraphAccessor.PROFILE_ID)
