import aio_pika
from aio_pika import Exchange, Channel
#поменять на абс
from typing import Optional

from aio_pika.abc import AbstractQueue, AbstractRobustConnection

from utils.config import CONFIG
from utils.logger import create_logger
from interface import AbstractConnectionBroker

log = create_logger("BrokerManager")


class ConnectionBrokerManager(AbstractConnectionBroker):
    def __init__(self,
                 queue_name: str,
                 key: str,
                 host: str = CONFIG.broker.host,
                 user: str = CONFIG.broker.user,
                 password: str = CONFIG.broker.password,
                 exchange: str = CONFIG.broker.exchange,
                 exchange_type: str = 'direct') -> None:
        self.host: str = host
        self.user: str = user
        self.password: str = password
        self.exchange_name: str = exchange
        self.exchange_type: str = exchange_type
        self.queue_name: str = queue_name

        self.exchange: Optional[Exchange] = None
        self.connection: Optional[AbstractRobustConnection] = None
        self.channel: Optional[Channel] = None
        self.queue: Optional[AbstractQueue] = None
        self.key = key

    async def connect(self) -> None:
        self.connection = await aio_pika.connect_robust(
            f"amqp://{self.user}:{self.password}@{self.host}/"
        )
        self.channel = await self.connection.channel()
        self.exchange = await self.channel.declare_exchange(
            self.exchange_name,
            self.exchange_type,
            durable=True
        )
        log.info("Подключено к брокеру")

        # dev only str
        self.queue = await self._create_queue(self.queue_name)
        await self._bind_exchange_as_queue(self.queue, routing_key=self.key)

    async def close(self) -> None:
        if self.connection:
            await self.connection.close()
            log.info("Подключение к брокеру закрыто")

    async def _create_queue(self, queue_name: str) -> AbstractQueue:
        queue: AbstractQueue = await self.channel.declare_queue(queue_name, durable=True)
        log.info(f"Создана очередь: {queue_name}")
        return queue

    async def _bind_exchange_as_queue(self, queue: AbstractQueue, routing_key: str) -> None:
        await queue.bind(self.exchange, routing_key=routing_key)
        log.info(f"Очередь {queue} привязана к {self.exchange}")

