import asyncio
import logging

from infrastructure.broker.interface import DeliveryDecision


logger = logging.getLogger(__name__)


async def declare_topology(broker):
    bindings = (
        ("parser.input", "parser.start.v1"),
        ("metrics.input", "graph.ready.v1"),
        ("harness.input", "metrics.ready.v1"),
        ("results", "harness.completed.v1"),
        ("errors", "*.failed.v1"),
    )

    for queue, routing_key in bindings:
        await broker.declare_queue(queue, routing_key)


class AsyncPublisher:

    def __init__(self, broker):
        self.broker = broker

    async def publish(self, event):
        await self.broker.publish(routing_key=event["event_type"], event=dict(event))

        logger.info("Published: %s", event["event_type"])


class SyncPublisher:

    def __init__(self, broker):
        self.publisher = AsyncPublisher(broker)
        self.loop = asyncio.get_running_loop()

    def publish(self, event):
        future = asyncio.run_coroutine_threadsafe(self.publisher.publish(event), self.loop)

        future.result()


def sync_consumer(handler, context):

    async def consume(event):
        logger.info("Received: %s", event["event_type"])

        decision = await asyncio.to_thread(handler, event, context)

        return DeliveryDecision(decision.value)

    return consume


def async_consumer(handler, context):

    async def consume(event):
        logger.info("Received: %s", event["event_type"])

        decision = await handler(event, context)

        return DeliveryDecision(decision.value)

    return consume