from pathlib import Path

from tools_engine.interface.engine import EngineInterface
from tools_engine.interface.tool import AbstractTool
from tools_engine.models.tool_models import ToolName, ExecuteToolData


class ToolsEngine(EngineInterface):
    def __init__(self):
        self.registered_tools: dict[ToolName, AbstractTool] = {}

    def start(self):
        """Запуск"""
        pass

    # def register_tool(self, tool: type[AbstractTool], source_index_path: str):
    #     """Регистрирует одну тулу"""
    #     source_index_path = Path(source_index_path)
    #
    #     if tool.name not in self.registered_tools.keys():
    #         self.registered_tools[tool.name] = tool(source_index_path)

    def register_tools(self, tools: list[type[AbstractTool]]):
        """Регистрирует множество тулов"""
        for tool in tools:
            self.registered_tools[tool.name] = tool()

    def entry_tool(self, source_index_path: Path, data: ExecuteToolData) -> str:
        """Исполняет любую тулу"""
        if data.name not in self.registered_tools.keys():
            raise

        tool = self.registered_tools[data.name]

        result = tool.execute(source_index_path, **data.context)

        return result
