import asyncio
import json
from typing import Optional

from aio_pika import RobustQueue

from infrastructure.broker.manager import ConnectionBrokerManager
from utils.logger import create_logger

log = create_logger("BrokerConsumer")

class Consumer:
    def __init__(self, connection:ConnectionBrokerManager):
        self.connection: ConnectionBrokerManager = connection
        self.queue: Optional[RobustQueue] = None

    async def start(self, queue_name):
        if not self.connection.channel:
            await self.connection.connect()


        queue = await self.connection.channel.declare_queue(queue_name, durable=True)
        log.info(f"Подписан на очередь: {queue_name}")

        await self.connection.channel.set_qos(prefetch_count=1) # одна задачу в один момент времени

        self.queue = queue

        log.info("Consumer готов")

    async def messages(self):
        """
        Асинхронный генератор, отдающий сообщения наружу.
        """
        if not self.connection.channel:
            raise RuntimeError("Брокер не подключен. Сначала вызови connect()")

        async with self.queue.iterator() as queue_iter:
            async for message in queue_iter:  # получаем входящие сообщения
                async with message.process():
                    try:
                        body = json.loads(message.body)
                        log.info(f"Получено сообщение: {body}")
                        yield body
                    except Exception as e:
                        log.error(f"Ошибка при чтении сообщения: {e}")


"""async def run():
    await con.connect()
    con.queue_task = await con._create_queue("tasks")
    con.queue_result  = await con._create_queue("result")
    await con._bind_exchange_as_queue(con.queue_task, "tasks")
    await con._bind_exchange_as_queue(con.queue_result, "result")

    consumer = Consumer(con)
    await consumer.start("tasks")

asyncio.run(run())"""