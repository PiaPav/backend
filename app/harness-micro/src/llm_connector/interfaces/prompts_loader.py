from abc import ABC, abstractmethod

from tools_engine.models.tool_models import ToolName


class PromptsLoaderInterface(ABC):

    @abstractmethod
    def load_prompt(self) -> str:
        """Загрузить промт для нейронки"""
        pass

    @abstractmethod
    def load_commands(self) -> str:
        """Загрузить команды, доступные нейронке"""
        pass

    @abstractmethod
    def load_tool(self, tool_name: ToolName) -> str:
        """Загружает промт для конкретной тулы"""
        pass
