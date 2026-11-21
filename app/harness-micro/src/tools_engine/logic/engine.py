import json

from response_models.models import ToolName
from tools_engine.interface.engine import EngineInterface, InvalidToolArguments
from tools_engine.interface.tool import AbstractTool
from tools_engine.models.analysis_context import AnalysisContext


class ToolsEngine(EngineInterface):
    def __init__(self):
        self.registered_tools: dict[ToolName, AbstractTool] = {}

    def start(self):
        """Запуск"""
        pass

    def register_tools(self, tools: list[type[AbstractTool]]):
        """Регистрирует множество тулов"""
        for tool in tools:
            self.registered_tools[tool.name] = tool()

    async def entry_tool(self, analysis_context: AnalysisContext, name: str, arguments: str) -> str:
        """Применить тулу

        :raises InvalidToolArguments: Если переданы неверные аргументы.
        """
        if ToolName(name) not in self.registered_tools.keys():
            raise

        tool = self.registered_tools[ToolName(name)]

        try:
            context = json.loads(arguments)

            result = tool.execute(analysis_context, **context)

        except json.JSONDecodeError as e:
            raise InvalidToolArguments(message=f"Аргументы: `{arguments}` не соответствуют формату JSON") from e

        return result
