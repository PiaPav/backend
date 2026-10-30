import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from metrics_service.contracts import PermanentError
from metrics_service.rabbit_adapter import declare_topology, process_delivery


def delivery():
    return SimpleNamespace(body=b"{}", headers={}, message_id="id", ack=AsyncMock(), reject=AsyncMock())


def test_ack_follows_handler_completion():
    async def scenario():
        message = delivery()
        async def handle(raw):
            message.ack.assert_not_awaited()
        await process_delivery(message, SimpleNamespace(handle=handle), AsyncMock(), "retry", 3)
        message.ack.assert_awaited_once()
    asyncio.run(scenario())


def test_retry_publication_must_succeed_before_ack():
    async def scenario():
        message, exchange = delivery(), AsyncMock()
        exchange.publish.side_effect = ConnectionError()
        handler = SimpleNamespace(handle=AsyncMock(side_effect=ConnectionError()))
        with pytest.raises(ConnectionError):
            await process_delivery(message, handler, exchange, "retry", 3)
        message.ack.assert_not_awaited()
        message.reject.assert_not_awaited()
    asyncio.run(scenario())


@pytest.mark.parametrize("error,attempt", [(PermanentError(), 0), (ConnectionError(), 3)])
def test_bad_or_exhausted_delivery_rejected(error, attempt):
    async def scenario():
        message, exchange = delivery(), AsyncMock()
        message.headers = {"metrics-retry": attempt}
        await process_delivery(message, SimpleNamespace(handle=AsyncMock(side_effect=error)), exchange, "retry", 3)
        message.reject.assert_awaited_once_with(requeue=False)
        message.ack.assert_not_awaited()
        exchange.publish.assert_not_awaited()
    asyncio.run(scenario())


def test_retry_is_persistent_bounded_and_confirmed_before_ack():
    async def scenario():
        message, exchange = delivery(), AsyncMock()
        async def publish(outgoing, **kwargs):
            message.ack.assert_not_awaited()
            assert outgoing.headers == {"metrics-retry": 1}
            assert outgoing.delivery_mode.value == 2
            assert kwargs == {"routing_key": "retry", "mandatory": True}
        exchange.publish.side_effect = publish
        await process_delivery(message, SimpleNamespace(handle=AsyncMock(side_effect=ConnectionError())), exchange, "retry", 3)
        message.ack.assert_awaited_once()
    asyncio.run(scenario())


def test_topology_includes_output_mailbox_and_delayed_retry():
    async def scenario():
        channel = AsyncMock()
        channel.declare_exchange.return_value = SimpleNamespace(name="exchange")
        queues = {}
        async def declare(name, **kwargs):
            queue = SimpleNamespace(name=name, bind=AsyncMock(), arguments=kwargs.get("arguments", {}))
            queues[name] = queue
            return queue
        channel.declare_queue.side_effect = declare
        settings = SimpleNamespace(exchange="events", queue="metrics", result_queue="results", retry_delay_ms=500)
        await declare_topology(channel, settings)
        assert queues["results"].bind.await_args.kwargs["routing_key"] == "metrics.ready.v1"
        assert queues["metrics.retry"].arguments["x-message-ttl"] == 500
        assert queues["metrics.retry"].arguments["x-dead-letter-routing-key"] == "metrics"
        assert queues["metrics"].arguments["x-dead-letter-routing-key"] == "failed"
        for queue in queues.values():
            assert queue.arguments["x-queue-type"] == "quorum"
        for name in ("metrics", "metrics.retry"):
            assert queues[name].arguments["x-dead-letter-strategy"] == "at-least-once"
            assert queues[name].arguments["x-overflow"] == "reject-publish"
    asyncio.run(scenario())
