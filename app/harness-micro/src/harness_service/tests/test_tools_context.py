import asyncio
from pathlib import Path

from response_models.models import ToolName
from tools_engine.interface.tool import AbstractTool
from tools_engine.logic.engine import ToolsEngine
from tools_engine.models.analysis_context import AnalysisContext
from tools_engine.registry import TOOL_REGISTRY, ToolDefinition


class ContextTool(AbstractTool):
    name = ToolName.Get_Content
    received = None

    def execute(self, analysis_context, **kwargs):
        type(self).received = analysis_context
        return kwargs["FILEPATH"]


def test_tools_engine_passes_analysis_context_to_tool() -> None:
    context = AnalysisContext(
        1, {"canonical.full": Path("graph")}, {"metrics.full": Path("metrics")},
        Path("index"), "a" * 64, "b" * 64,
    )
    definition = ToolDefinition(
        ToolName.Get_Content, ContextTool, TOOL_REGISTRY[0].schema_path
    )
    engine = ToolsEngine((definition,))

    result = asyncio.run(engine.entry_tool(context, ToolName.Get_Content, '{"FILEPATH":"ok"}'))

    assert result.status == "success"
    assert result.result == "ok"
    assert ContextTool.received is context
