from abc import ABC, abstractmethod
from pathlib import Path

from tools_engine.models.tool_models import ExecuteToolData


class EngineInterface(ABC):

    @abstractmethod
    def start(self):
        """Запуск"""
        pass

    # @abstractmethod
    # def register_tool(self, tool: AbstractTool, source_index_path: str):
    #     """Регистрация тулы в сервере"""
    #     pass
    #
    # @abstractmethod
    # def register_tools(self, tools: list[type[AbstractTool]], source_index_path: str):
    #     """Регистрация списка тулов в сервере"""
    #     pass

    @abstractmethod
    def entry_tool(self, source_index_path: Path, data: ExecuteToolData) -> str:
        """Применить тулу"""
        pass
