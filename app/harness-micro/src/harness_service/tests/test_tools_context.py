import asyncio
from pathlib import Path

from response_models.models import ToolName
from tools_engine.interface.tool import AbstractTool
from tools_engine.logic.engine import ToolsEngine
from tools_engine.models.analysis_context import AnalysisContext


class ContextTool(AbstractTool):
    name = ToolName.Get_Content
    received = None

    def execute(self, analysis_context, **kwargs):
        type(self).received = analysis_context
        return kwargs["value"]


def test_tools_engine_passes_analysis_context_to_tool() -> None:
    context = AnalysisContext(
        1, {"canonical.full": Path("graph")}, {"metrics.full": Path("metrics")},
        Path("index"), "a" * 64, "b" * 64,
    )
    engine = ToolsEngine()
    engine.register_tools([ContextTool])

    result = asyncio.run(engine.entry_tool(context, ToolName.Get_Content, '{"value":"ok"}'))

    assert result == "ok"
    assert ContextTool.received is context
