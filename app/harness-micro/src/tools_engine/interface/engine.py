from abc import ABC, abstractmethod
from tools_engine.models.analysis_context import AnalysisContext
from tools_engine.models.tool_result import ToolResult


class EngineInterface(ABC):

    @abstractmethod
    def start(self):
        """Запуск"""
        pass

    @abstractmethod
    async def entry_tool(self, analysis_context: AnalysisContext, name: str, arguments: str) -> ToolResult:
        """Применить инструмент."""
        pass
