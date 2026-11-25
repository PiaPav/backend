import asyncio
import logging
import os

from pathlib import Path

from infrastructure.broker import RabbitMQManager
from infrastructure.broker_adapters import (
    SyncPublisher,
    sync_consumer,
    declare_topology,
)

from .composition import LocalSettings, build_application
from .application.models import DeliveryContext


async def main():
    logging.basicConfig(level=logging.INFO)

    broker = RabbitMQManager(url=os.environ["RABBITMQ_URL"])

    await broker.connect(prefetch_count=1)

    try:
        await declare_topology(broker)

        settings = LocalSettings(
            source_root=Path("/data/sources"),
            staging_root=Path("/data/staging/parser"),
            artifact_root=Path("/data/graphs"),
            idempotency_database=Path("/state/parser.db"),
            producer_version="1",
        )

        handler = build_application(settings, publisher=SyncPublisher(broker))

        context = DeliveryContext(authorized_tenant_id=os.environ["TENANT_ID"])

        await broker.consume(queue_name="parser.input", routing_key="parser.start.v1", handler=sync_consumer(handler, context))

        logging.info("Parser is ready")

        await asyncio.Event().wait()

    finally:
        await broker.close()


if __name__ == "__main__":
    asyncio.run(main())