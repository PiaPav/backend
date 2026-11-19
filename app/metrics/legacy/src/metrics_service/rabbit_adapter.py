"""Confirmed publications precede acknowledgement, including delayed retry."""
import logging

import aio_pika

from .contracts import PermanentError, encode

logger = logging.getLogger(__name__)


class RabbitPublisher:
    def __init__(self, exchange):
        self.exchange = exchange

    async def publish(self, event: dict) -> None:
        await self.exchange.publish(aio_pika.Message(
            encode(event), content_type="application/json", message_id=event["event_id"],
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        ), routing_key=event["event_type"], mandatory=True)


async def declare_topology(channel, settings):
    exchange = await channel.declare_exchange(settings.exchange, aio_pika.ExchangeType.TOPIC, durable=True)
    results = await channel.declare_queue(settings.result_queue, durable=True,
                                          arguments={"x-queue-type": "quorum"})
    await results.bind(exchange, routing_key="metrics.ready.v1")
    dead = await channel.declare_exchange(settings.queue + ".dead", aio_pika.ExchangeType.DIRECT, durable=True)
    dlq = await channel.declare_queue(settings.queue + ".dlq", durable=True,
                                     arguments={"x-queue-type": "quorum"})
    await dlq.bind(dead, routing_key="failed")
    queue = await channel.declare_queue(settings.queue, durable=True, arguments={
        "x-queue-type": "quorum", "x-dead-letter-strategy": "at-least-once",
        "x-overflow": "reject-publish",
        "x-dead-letter-exchange": dead.name, "x-dead-letter-routing-key": "failed",
    })
    await queue.bind(exchange, routing_key="graph.ready.v1")
    retry = await channel.declare_queue(settings.queue + ".retry", durable=True, arguments={
        "x-queue-type": "quorum", "x-dead-letter-strategy": "at-least-once",
        "x-overflow": "reject-publish",
        "x-message-ttl": settings.retry_delay_ms,
        "x-dead-letter-exchange": "", "x-dead-letter-routing-key": settings.queue,
    })
    return exchange, queue, retry


async def process_delivery(message, handler, retry_exchange, retry_queue: str, max_retries: int):
    try:
        await handler.handle(message.body)
    except PermanentError:
        logger.warning("metrics input rejected", extra={"message_id": message.message_id})
        await message.reject(requeue=False)
        return
    except Exception:
        # Do not log exception text: SDK errors can contain credentials or payloads.
        logger.warning("metrics processing failed", extra={"message_id": message.message_id})
        attempt = message.headers.get("metrics-retry", 0)
        if type(attempt) is not int or attempt < 0 or attempt >= max_retries:
            await message.reject(requeue=False)
            return
        try:
            await retry_exchange.publish(aio_pika.Message(
                message.body, content_type="application/json", message_id=message.message_id,
                headers={"metrics-retry": attempt + 1}, delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            ), routing_key=retry_queue, mandatory=True)
        except Exception:
            # Let the supervisor close the channel, returning the unacked delivery.
            raise
    await message.ack()
