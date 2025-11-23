import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))
import asyncio

from infrastructure.broker.consumer import Consumer
from infrastructure.broker.manager import ConnectionBrokerManager
from services.parse_service import run_parse_microservice
from utils.logger import create_logger


log = create_logger("MainService")

async def main():
    conn = ConnectionBrokerManager(
        queue_name="parse_tasks",
        key="parse.start"
    )
    consumer = Consumer(conn)

    await conn.connect()
    log.info(f"Готов к получению сообщений")

    async for msg in consumer.messages():
        task_id = msg["task_id"]
        project_path = msg["project_path"]
        log.info(f"Получена задача: {msg}")

        asyncio.create_task(run_parse_microservice(task_id, project_path))


asyncio.run(main())
