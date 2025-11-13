from infrastructure.broker.producer import Producer
from infrastructure.broker.interface import AbstractConnectionBroker
from utils.logger import create_logger

from infrastructure.broker.manager import ConnectionBrokerManager


log  = create_logger("BrokerManagerService")


class BrokerManager:
    def __init__(self, repo: AbstractConnectionBroker):
        self.repo = repo
        self.producer = Producer(repo)

    async def publish(self, routing_key: str, message: dict):
        """Отправка сообщения с повторными попытками через Producer."""
        try:
            await self.producer.publish(routing_key, message)
            return
        except Exception as e:
            log.error(f"Ошибка при вызове инфраструктуры в сервисном слое {routing_key}: {e}")
            raise

broker_repo_task = ConnectionBrokerManager(queue_name="tasks", key="tasks")
broker_manager = BrokerManager(broker_repo_task)