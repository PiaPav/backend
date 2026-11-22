from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from response_models.models import ToolName
from tools_engine.models.analysis_context import AnalysisContext


class AbstractTool(ABC):
    name: ToolName


    @abstractmethod
    def execute(self, analysis_context: AnalysisContext, **kwargs):
        """Запуск команды"""
        pass


class ToolError(Exception):
    default_code = "tool_error"
    default_message = "Ошибка инструмента"
    default_retryable = False

    def __init__(self, message: str | None = None, details: dict[str, Any] | None = None,
                 retryable: bool | None = None, *, code: str | None = None):
        self.code = code or self.default_code
        self.message = message or self.default_message
        self.details = details or {}
        self.retryable = self.default_retryable if retryable is None else retryable
        super().__init__(message)

    @property
    def name(self) -> str:
        return self.__class__.__name__

    def __str__(self):
        return f"{self.name}: {self.code}: {self.message}"


class InvalidToolArguments(ToolError):
    default_code = "invalid_tool_arguments"
    default_message = "Неверные аргументы для инструмента"
    default_retryable = True


class UnknownTool(ToolError):
    default_code = "unknown_tool"
    default_message = "Неизвестный инструмент"
    default_retryable = True


class SourceObjectNotFound(ToolError):
    default_code = "source_object_not_found"
    default_message = "Объект исходного кода не найден"
    default_retryable = True


class ExtractionLimitExceeded(ToolError):
    default_code = "extraction_limit_exceeded"
    default_message = "Превышен допустимый размер извлечения"
    default_retryable = True


class InvalidArtifact(ToolError):
    default_code = "invalid_artifact"
    default_message = "Артефакт повреждён или имеет неверный формат"
    default_retryable = False


class ProfileNotFound(ToolError):
    default_code = "profile_not_found"
    default_message = "Профиль не найден"
    default_retryable = True


class NodeNotFound(ToolError):
    default_code = "node_not_found"
    default_message = "Узел графа не найден"
    default_retryable = True


class MetricPathNotFound(ToolError):
    default_code = "metric_path_not_found"
    default_message = "Путь показателя не найден"
    default_retryable = True
