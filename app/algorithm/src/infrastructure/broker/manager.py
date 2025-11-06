import aio_pika
from aio_pika import Exchange, RobustConnection, Channel, Message
from typing import Optional

from aio_pika.abc import AbstractQueue

from utils.config import CONFIG
from utils.logger import create_logger

log = create_logger("BrokerManager")


class ConnectionBrokerManager:
    def __init__(self,
                 host: str = CONFIG.broker.host,
                 user: str = CONFIG.broker.user,
                 password: str = CONFIG.broker.password,
                 exchange: str = CONFIG.broker.exchange,
                 queue_task_name: str = CONFIG.broker.queue_task,
                 queue_result_name: str = CONFIG.broker.queue_result,
                 exchange_type: str = 'direct') -> None:
        self.host: str = host
        self.user: str = user
        self.password: str = password
        self.exchange_name: str = exchange
        self.exchange_type: str = exchange_type
        self.queue_task_name: str = queue_task_name
        self.queue_result_name: str = queue_result_name

        self.exchange: Optional[Exchange] = None
        self.connection: Optional[RobustConnection] = None
        self.channel: Optional[Channel] = None
        self.queue_task: Optional[AbstractQueue] = None
        self.queue_result: Optional[AbstractQueue] = None
        self.task_key = "tasks"
        self.result_key = "result"


    async def connect(self) -> None:
        self.connection = await aio_pika.connect_robust(
            f"amqp://{self.user}:{self.password}@{self.host}/"
        )
        self.channel = await self.connection.channel()
        self.exchange = await self.channel.declare_exchange(
            self.exchange_name,  # TODO поменять имя на другое, тк это другая сущность
            self.exchange_type,
            durable=True
        )
        log.info("Подключено к брокеру")


    async def close(self) -> None:
        if self.connection:
            await self.connection.close()
            log.info("Подключение к брокеру закрыто")


    async def _create_queue(self, queue_name: str) ->AbstractQueue:
        queue: AbstractQueue = await self.channel.declare_queue(queue_name, durable=True) #TODO разобраться с аннотацией либо с пайчармом
        log.info(f"Создана очередь: {queue_name}")
        return queue


    async def _bind_exchange_as_queue(self, queue:AbstractQueue, routing_key: str) -> None:
        await queue.bind(self.exchange, routing_key=routing_key)
        log.info(f"Очередь {queue} привязана к {self.exchange}")

