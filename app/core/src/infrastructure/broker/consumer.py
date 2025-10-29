import asyncio
import json
import aio_pika

from aio_pika.abc import AbstractIncomingMessage

from manager import ConnectionBrokerManager
from producer import Producer
from utils.config import CONFIG
from utils.logger import create_logger

log = create_logger("Consumer_Core")

class Consumer:
    def __init__(self, connection:ConnectionBrokerManager):
        self.connection = connection
        self.producer = Producer(connection)

    async def start(self, queue_name):
        """подписано в процесс через корутину (через евентлуп)"""
        if not self.connection.channel:
            raise RuntimeError("Брокер не подключен.")

        queue = await self.connection.channel.declare_queue(queue_name, durable=True)
        log.info(f"Подписан на очередь: {queue_name}")

        await self.connection.channel.set_qos(prefetch_count=1) # одна задачу в один момент времени

        await queue.consume(self._on_message)
        log.info("Ожидание сообщений")
        await asyncio.Future()  # магия ебанная

    async def _on_message(self, message: AbstractIncomingMessage):
        async with message.process():
            try:
                body = json.loads(message.body)
                log.info(f"Получено сообщение: {body}")

                result = await self.handle_task(body)

                await self.producer.publish("result", result) #по хорошему надо указывать неявное имя
                log.info(f"Отправлен результат: {result}")

            except Exception as e:
                log.error(f"Ошибка при обработке сообщения: {e}")

    async def handle_task(self, task: dict) -> dict:
        """чисто логика обрабоки, скорее всего инверсию бизнес логики писать сюда"""
        log.info(f"Обработка задачи: {task}")

        result = {
                "task_id": task.get("task_id"),
                "status": "done",
                "processed_text": task.get("text", "").upper()
            }

        await void_word()

        return result


async def void_word():
    await asyncio.sleep(2)
    return True