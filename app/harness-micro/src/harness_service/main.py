import asyncio
import logging
import os

from infrastructure.broker.manager import RabbitMQManager
from infrastructure.broker_adapters import (
    AsyncPublisher,
    declare_topology,
)
from infrastructure.broker.interface import DeliveryDecision

from .composition import build_handler
from .harness_handler import DeliveryContext

from pathlib import Path
from .local_adapters import LocalInputMaterializer, LocalResultStore, InMemoryIdempotencyStore
from utils.config import CONFIG


def to_harness_event(event):
    payload = event["payload"]

    return {
        **event,
        "event_id": f"{event['event_id']}:harness-start",
        "event_type": "harness.start.v1",
        "causation_id": event["event_id"],
        "producer": {
            "service": "harness-adapter",
            "version": "1",
        },
        "payload": {
            "source_uri": payload["source_uri"],
            "graph": payload["graph"],
            "metrics": payload["metrics"],
            "source_index": payload["source_index"],
        },
    }


async def main(materializer, result_store, idempotency):
    logging.basicConfig(level=logging.INFO)

    broker = RabbitMQManager(url=os.environ["RABBITMQ_URL"])

    await broker.connect(prefetch_count=1)

    try:
        await declare_topology(broker)

        handler = await build_handler(
            llm_url=CONFIG.llm.url,
            llm_api_key=CONFIG.llm.apikey,
            materializer=materializer,
            result_store=result_store,
            idempotency=idempotency,
            publisher=AsyncPublisher(broker),
            concurrency=1,
        )

        context = DeliveryContext(authorized_tenant_id=os.environ["TENANT_ID"])

        async def consume(event):
            logging.info("Received: %s", event["event_type"])

            try:
                harness_event = to_harness_event(event)
            except (KeyError, TypeError, ValueError):
                logging.exception("Invalid metrics event")
                return DeliveryDecision.REJECT

            decision = await handler.handle(harness_event, context)

            return DeliveryDecision(decision.value)

        await broker.consume(queue_name="harness.input", routing_key="metrics.ready.v1", handler=consume)

        logging.info("Harness is ready")

        await asyncio.Event().wait()

    finally:
        await broker.close()


if __name__ == "__main__":
    asyncio.run(main(
        materializer=LocalInputMaterializer(),
        result_store=LocalResultStore(Path("/data/results")),
        idempotency=InMemoryIdempotencyStore(),
    ))