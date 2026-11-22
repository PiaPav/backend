from response_models.models import ToolName
from tools_engine.accessors.graph import GraphAccessor
from tools_engine.interface.tool import AbstractTool, InvalidToolArguments
from tools_engine.models.analysis_context import AnalysisContext
from tools_engine.models.tool_result import ToolOutput


class GetGraph(AbstractTool):
    name = ToolName.Get_Graph

    def execute(self, analysis_context: AnalysisContext, **kwargs):
        profile_id = kwargs["PROFILE-ID"]
        if not profile_id:
            raise InvalidToolArguments("PROFILE-ID не должен быть пустым")
        return ToolOutput(
            GraphAccessor(analysis_context).raw(profile_id), profile_id=profile_id
        )
