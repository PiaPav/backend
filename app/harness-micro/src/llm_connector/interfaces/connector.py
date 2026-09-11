import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from enum import StrEnum


class MessageAuthors(StrEnum):
    agent = "AGENT"
    user = "USER"


@dataclass
class Message:
    author: MessageAuthors
    instructions: str
    content: str

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


class AbstractLLMSession(ABC):

    @abstractmethod
    async def send(self, message: Message) -> str:
        """Отправить запрос"""
        pass

    # @abstractmethod
    # async def receive(self):
    #     """Извлечь результат"""
    #     pass


class LLMConnectorInterface(ABC):

    @abstractmethod
    async def create_session(self, unique_id: int) -> AbstractLLMSession:
        """Получить сессию для общения с нейронкой"""
        pass

    @abstractmethod
    async def connect(self, url, apikey):
        """Подключиться к апи"""
        pass
