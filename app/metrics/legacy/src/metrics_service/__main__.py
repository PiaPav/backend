"""Composition root with bounded, sequential consumption and graceful shutdown."""
import asyncio
import logging
import signal

import aioboto3
import aio_pika
from botocore.config import Config

from .application import MetricsHandler
from .core_adapter import CoreMetricsEngine
from .rabbit_adapter import RabbitPublisher, declare_topology, process_delivery
from .s3_adapter import S3ArtifactStore
from .settings import Settings


async def main():
    settings = Settings.from_env()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    connection = await aio_pika.connect(
        host=settings.rabbit_host, port=settings.rabbit_port, login=settings.rabbit_user,
        password=settings.rabbit_password, virtualhost=settings.rabbit_vhost,
    )
    async with connection:
        channel = await connection.channel(publisher_confirms=True, on_return_raises=True)
        await channel.set_qos(prefetch_count=1)
        exchange, queue, retry = await declare_topology(channel, settings)
        session = aioboto3.Session()
        async with session.client("s3", endpoint_url=settings.s3_endpoint,
                                  aws_access_key_id=settings.s3_access, aws_secret_access_key=settings.s3_secret,
                                  config=Config(connect_timeout=10, read_timeout=30, retries={"max_attempts": 3})) as client:
            await client.head_bucket(Bucket=settings.bucket)
            handler = MetricsHandler(S3ArtifactStore(client, settings.bucket), RabbitPublisher(exchange),
                                     CoreMetricsEngine(), settings.bucket, settings.max_graph_bytes,
                                     settings.max_metrics_bytes)
            async with queue.iterator() as messages:
                logging.getLogger(__name__).info("metrics service ready")
                while not stop.is_set():
                    incoming = asyncio.create_task(anext(messages))
                    stopping = asyncio.create_task(stop.wait())
                    done, _ = await asyncio.wait((incoming, stopping), return_when=asyncio.FIRST_COMPLETED)
                    if incoming in done:
                        stopping.cancel()
                        await asyncio.gather(stopping, return_exceptions=True)
                        await process_delivery(incoming.result(), handler, channel.default_exchange,
                                               retry.name, settings.max_retries)
                    else:
                        incoming.cancel()
                        await asyncio.gather(incoming, return_exceptions=True)
                        break


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
