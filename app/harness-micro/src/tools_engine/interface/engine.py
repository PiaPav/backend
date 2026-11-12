from abc import ABC, abstractmethod
from pathlib import Path


class EngineInterface(ABC):

    @abstractmethod
    def start(self):
        """Запуск"""
        pass

    @abstractmethod
    def entry_tool(self, source_index_path: Path, name: str, arguments: str) -> str:
        """Применить тулу"""
        pass
