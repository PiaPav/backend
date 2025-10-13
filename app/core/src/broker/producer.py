import aio_pika
import json

from utils.config import CONFIG
from utils.logger import create_logger

log = create_logger("BrokerProducer")

class Producer:
    def __init__(self,
                 host: str = CONFIG.broker.host,
                 user: str = CONFIG.broker.user,
                 password: str = CONFIG.broker.password,
                 exchange=CONFIG.broker.queue,
                 exchange_type='direct'):
        self.host = host
        self.user = user
        self.password = password
        self.exchange = exchange
        self.exchange_type = exchange_type
        self.connection = None
        self.channel = None

    async def _connect(self):
        self.connection = await aio_pika.connect_robust(f"amqp://{self.user}:{self.password}@{self.host}/")
        self.channel = self.connection.channel()
        self.exchange = await self.channel.declare_exchange(
            self.exchange, self.exchange_type, durable=True
        )
        log.info("Подключено к брокеру")

    async def close(self):
        await self.connection.close()
        log.info("Подключение к брокеру закрыто")

    async def publish(self, routing_key: str, message: dict, persistent=True):
        body = json.dumps(message).encode()
        msg = aio_pika.Message(
            body,
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT if persistent else aio_pika.DeliveryMode.NOT_PERSISTENT,
        )
        await self.exchange.publish(msg, routing_key=routing_key)
        log.info(f"отправлено {routing_key}: {message}")


producer = Producer()




