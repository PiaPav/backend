from abc import ABC, abstractmethod
from pathlib import Path


class InvalidToolArguments(Exception):
    default: str = "Неверные аргументы для инструмента"

    def __init__(self, message: str, details: dict = None, *args, **kwargs):
        message = self.default + message
        self.error = {"message": message, "details": details}
        super().__init__(message)

    @property
    def name(self) -> str:
        return self.__class__.__name__

    def __str__(self):
        return f"{self.name}: {self.error}"


class EngineInterface(ABC):

    @abstractmethod
    def start(self):
        """Запуск"""
        pass

    @abstractmethod
    async def entry_tool(self, source_index_path: Path, name: str, arguments: str) -> str:
        """Применить тулу

        :raises InvalidToolArguments: Если переданы неверные аргументы.
        """
        pass
