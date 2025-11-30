import asyncio
import json
from typing import Optional

from aio_pika import RobustQueue

from interface import AbstractConnectionBroker
from utils.logger import create_logger

log = create_logger("BrokerConsumer")


class Consumer:
    def __init__(self, connection: AbstractConnectionBroker):
        self.connection: AbstractConnectionBroker = connection
        self.queue: Optional[RobustQueue] = None

    async def start(self):
        if not self.connection.channel:
            await self.connection.connect()

        await self.connection.channel.set_qos(prefetch_count=1)  # одна задачу в один момент времени
        log.info("Ожидание сообщений")

        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            log.info("Consumer остановлен.")

    async def messages(self):
        """
        Асинхронный генератор, отдающий сообщения наружу.
        """
        if not self.connection.channel:  # невозможно?
            raise RuntimeError("Брокер не подключен. Сначала вызови connect()")

        async with self.queue.iterator() as queue_iter:
            async for message in queue_iter:  # получаем сообщения
                async with message.process():
                    try:
                        body = json.loads(message.body)
                        log.info(f"Получено сообщение: {body}")
                        yield body
                    except Exception as e:
                        log.error(f"Ошибка при чтении сообщения: {e}")
