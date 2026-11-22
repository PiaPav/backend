from response_models.models import ToolName
from tools_engine.accessors.metrics import MetricsAccessor
from tools_engine.interface.tool import AbstractTool, InvalidToolArguments
from tools_engine.models.analysis_context import AnalysisContext
from tools_engine.models.tool_result import ToolOutput


class GetMetricsItem(AbstractTool):
    name = ToolName.Get_Metrics_Item

    def execute(self, analysis_context: AnalysisContext, **kwargs):
        profile_id = kwargs["PROFILE-ID"]
        if not profile_id:
            raise InvalidToolArguments("PROFILE-ID не должен быть пустым")
        value = MetricsAccessor(analysis_context, profile_id).get(kwargs["METRIC-PATH"])
        return ToolOutput(value, profile_id=profile_id)
