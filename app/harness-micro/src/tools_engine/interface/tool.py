from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from response_models.models import ToolName


class AbstractTool(ABC):
    name: ToolName


    @abstractmethod
    def execute(self, source_index_path: Path, **kwargs):
        """Запуск команды"""
        pass


class ToolError(Exception):

    def __init__(self, message: str, details: dict = None, *args, **kwargs):
        self.error = {"message": message, "details": details}
        super().__init__(message)

    @property
    def name(self) -> str:
        return self.__class__.__name__

    def __str__(self):
        return f"{self.name}: {self.error}"


class ExceedingExtractionLimit(ToolError):
    """Ошибка чрезмерного размера извлекаемого объекта"""
    pass


class UnexpectedFileType(ToolError):
    """Неожиданный тип файла"""
    pass
