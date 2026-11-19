from abc import ABC, abstractmethod
from typing import Literal

from llm_connector.interfaces.prompts_loader import PromptsLoaderInterface
from response_models.models import Prompt, ToolResponse, ToolData, ToolCall


class ValidatorInterface(ABC):

    @abstractmethod
    def __init__(self, prompts_loader: PromptsLoaderInterface):
        pass

    @abstractmethod
    def create_start_messages(self, graph, metrix) -> list[Prompt]:
        """Создает и валидирует сообщение"""
        pass

    @abstractmethod
    def load_tools_models(self) -> list[ToolData]:
        pass

    @abstractmethod
    def create_tool_message(self, tool_call: ToolCall, status: Literal["success", "error", "deny"], data: str = None,
                            msg: str = None, retryable: bool = None) -> ToolResponse:
        """Создает сообщения с информацией из тулы для нейронки"""
        pass

    @abstractmethod
    def create_message(self, msg: str) -> Prompt:
        """Создает сообщение с текстом"""
        pass
