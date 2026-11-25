import logging
import os

from database.projects import Project
from infrastructure.broker.interface import DeliveryDecision


log = logging.getLogger(__name__)


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


async def consume_result(event: dict) -> DeliveryDecision:
    try:
        if event["event_type"] != "harness.completed.v1":
            return DeliveryDecision.REJECT

        if event["tenant_id"] != os.environ["TENANT_ID"]:
            return DeliveryDecision.REJECT

        correlation_id = event["correlation_id"]
        result_uri = event["payload"]["result"]["uri"]

        if not isinstance(correlation_id, str) or not isinstance(result_uri, str):
            return DeliveryDecision.REJECT

    except (KeyError, TypeError):
        return DeliveryDecision.REJECT

    updated = await Project.set_result(correlation_id, result_uri)

    if updated:
        log.info("Analysis completed: %s", correlation_id)
    else:
        log.warning("Unknown project: %s", correlation_id)

    return DeliveryDecision.ACK


async def consume_error(event: dict) -> DeliveryDecision:
    try:
        if event["tenant_id"] != os.environ["TENANT_ID"]:
            return DeliveryDecision.REJECT

        correlation_id = event["correlation_id"]
        error = str(event["payload"])

        if not isinstance(correlation_id, str):
            return DeliveryDecision.REJECT

    except (KeyError, TypeError):
        return DeliveryDecision.REJECT

    await Project.set_failed(correlation_id, error)

    return DeliveryDecision.ACK