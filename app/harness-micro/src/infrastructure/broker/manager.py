import json

import aio_pika
from aio_pika import DeliveryMode, ExchangeType, IncomingMessage, Message

from .interface import BrokerInterface, Handler, DeliveryDecision


class RabbitMQManager(BrokerInterface):
    def __init__(self, url: str, exchange_name: str = "analysis.events") -> None:
        self.url = url
        self.exchange_name = exchange_name
        self.connection: aio_pika.RobustConnection | None = None
        self.channel: aio_pika.abc.AbstractRobustChannel | None = None
        self.exchange: aio_pika.abc.AbstractRobustExchange | None = None

    async def connect(self, prefetch_count: int = 2) -> None:
        self.connection = await aio_pika.connect_robust(self.url)
        self.channel = await self.connection.channel(publisher_confirms=True)
        await self.channel.set_qos(prefetch_count=prefetch_count)
        self.exchange = await self.channel.declare_exchange(self.exchange_name, ExchangeType.TOPIC, durable=True)

    async def publish(self, routing_key: str, event: dict) -> None:
        if self.exchange is None:
            raise RuntimeError("RabbitMQ manager is not connected")

        body = json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        message = Message(body=body, content_type="application/json", delivery_mode=DeliveryMode.PERSISTENT)
        await self.exchange.publish(message, routing_key=routing_key)

    async def consume(self, queue_name: str, routing_key: str, handler: Handler) -> None:
        if self.channel is None or self.exchange is None:
            raise RuntimeError("RabbitMQ manager is not connected")

        queue = await self.channel.declare_queue(queue_name, durable=True)
        await queue.bind(self.exchange, routing_key=routing_key)

        async def on_message(message: IncomingMessage) -> None:
            try:
                event = json.loads(message.body.decode("utf-8"))
                decision = await handler(event)
            except (UnicodeDecodeError, json.JSONDecodeError):
                await message.reject(requeue=False)
                return
            except Exception:
                await message.reject(requeue=True)
                return

            if decision is DeliveryDecision.ACK:
                await message.ack()
            elif decision is DeliveryDecision.RETRY:
                await message.reject(requeue=True)
            else:
                await message.reject(requeue=False)

        await queue.consume(on_message, no_ack=False)

    async def close(self) -> None:
        if self.connection is not None:
            await self.connection.close()
