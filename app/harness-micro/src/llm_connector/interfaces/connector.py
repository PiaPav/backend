from abc import ABC, abstractmethod

from response_models.models import Prompt, ToolData, ModelResponse, ToolResponse


class AbstractLLMSession(ABC):

    @abstractmethod
    async def send_start(self, messages: list[Prompt], tools: list[ToolData]) -> ModelResponse:
        """Отправить стартовый запрос"""
        pass

    @abstractmethod
    def close(self) -> bool:
        pass

    @abstractmethod
    async def send(self, messages: list[Prompt | ToolResponse]) -> ModelResponse:
        """Отправить запрос"""
        pass


class LLMConnectorInterface(ABC):

    @abstractmethod
    async def create_session(self, unique_id: int) -> AbstractLLMSession:
        """Получить сессию для общения с нейронкой"""
        pass

    @abstractmethod
    async def close_session(self, session_id: int) -> bool:
        pass

    @abstractmethod
    async def connect(self, url, apikey):
        """Подключиться к апи"""
        pass
