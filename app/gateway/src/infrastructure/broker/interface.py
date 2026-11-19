from abc import ABC, abstractmethod
from typing import Optional

from aio_pika import Exchange, Channel
from aio_pika.abc import AbstractQueue, AbstractRobustConnection


class AbstractConnectionBroker(ABC):
    exchange: Optional[Exchange] = None
    connection: Optional[AbstractRobustConnection] = None
    channel: Optional[Channel] = None
    queue: Optional[AbstractQueue] = None

    @abstractmethod
    async def connect(self) -> None:
        pass

    @abstractmethod
    async def close(self) -> None:
        pass
