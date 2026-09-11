from abc import ABC, abstractmethod
from pathlib import Path

from tools_engine.models.tool_models import ToolName


class AbstractTool(ABC):
    name: ToolName

    # @abstractmethod
    # def check_permission(self):
    #     """Проверить условия запуска: входные параметры, права и т.п."""
    #     pass

    @abstractmethod
    def execute(self, source_index_path: Path, **kwargs):
        """Запуск команды"""
        pass
