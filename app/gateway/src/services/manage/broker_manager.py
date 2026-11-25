import os

from infrastructure.broker.manager import RabbitMQManager


broker_manager = RabbitMQManager(
    url=os.environ["RABBITMQ_URL"],
)
