import aio_pika
import json
from aio_pika import Message


from utils.logger import create_logger
from interface import AbstractConnectionBroker
log = create_logger("BrokerProducer")


class Producer:
    def __init__(self,connection:AbstractConnectionBroker):
        self.connection:AbstractConnectionBroker = connection

    async def publish(self, routing_key: str, message: dict, persistent: bool = True) -> None:
        try:
            body: bytes = json.dumps(message).encode()
            msg: Message = aio_pika.Message(
                body,
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT if persistent else aio_pika.DeliveryMode.NOT_PERSISTENT,
            )
            await self.connection.exchange.publish(msg, routing_key=routing_key)
            log.info(f"Отправлено {routing_key}: {message}")
        except Exception as e:
            log.error(f"Ошибка при отправке сообщения {e}")