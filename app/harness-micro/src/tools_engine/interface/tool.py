from abc import ABC, abstractmethod
from pathlib import Path

from response_models.models import ToolName


class AbstractTool(ABC):
    name: ToolName


    @abstractmethod
    def execute(self, source_index_path: Path, **kwargs):
        """Запуск команды"""
        pass
