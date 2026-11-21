from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Awaitable, Callable


class DeliveryDecision(StrEnum):
    ACK = "ack"
    RETRY = "retry"
    REJECT = "reject"


Handler = Callable[[dict], Awaitable[DeliveryDecision]]


class BrokerInterface(ABC):

    @abstractmethod
    def __init__(self, url: str, exchange_name: str = "analysis.events") -> None:
        pass

    @abstractmethod
    async def connect(self, prefetch_count: int = 2) -> None:
        pass

    @abstractmethod
    async def publish(self, routing_key: str, event: dict) -> None:
        pass

    @abstractmethod
    async def consume(self, queue_name: str, routing_key: str, handler: Handler) -> None:
        pass

    @abstractmethod
    async def close(self) -> None:
        pass
