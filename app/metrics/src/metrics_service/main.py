import asyncio
import logging
import os

from pathlib import Path

from infrastructure.broker.manager import RabbitMQManager
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
            graph_root=Path("/data/graphs"),
            staging_root=Path("/data/staging/metrics"),
            artifact_root=Path("/data/metrics"),
            idempotency_database=Path("/state/metrics.db"),
            producer_version="1",
        )

        handler = build_application(settings, publisher=SyncPublisher(broker))

        context = DeliveryContext(authorized_tenant_id=os.environ["TENANT_ID"])

        await broker.consume(queue_name="metrics.input", routing_key="graph.ready.v1", handler=sync_consumer(handler, context))

        logging.info("Metrics is ready")

        await asyncio.Event().wait()

    finally:
        await broker.close()


if __name__ == "__main__":
    asyncio.run(main())