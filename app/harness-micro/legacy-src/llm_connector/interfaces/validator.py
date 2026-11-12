from abc import ABC, abstractmethod

from llm_connector.interfaces.connector import Message
from llm_connector.interfaces.prompts_loader import PromptsLoaderInterface
from tools_engine.models.tool_models import ToolName, LLMResponse


class ValidatorInterface(ABC):

    @abstractmethod
    def __init__(self, prompts_loader: PromptsLoaderInterface):
        pass

    @abstractmethod
    def create_message(self, graph, metrix) -> Message:
        """Создает и валидирует сообщение"""
        pass

    @abstractmethod
    def validate_response(self, data: str) -> LLMResponse:
        """Валидирует ответ нейронки"""
        pass

    @abstractmethod
    def create_tool_message(self, tool_name: ToolName, data: str) -> Message:
        """Создает сообщения с информацией из тулы для нейронки"""
        pass
