import os
from dataclasses import dataclass

from dotenv import load_dotenv

# Загружаем переменные из .env файла
load_dotenv()


@dataclass
class ConfigServer:
    host: str
    port: int

@dataclass
class ConfigBroker:
    host: str
    queue_task: str
    queue_result: str
    user: str
    password: str
    exchange: str

@dataclass
class Config:
    server: ConfigServer
    broker: ConfigBroker


def load_config() -> Config:
    return Config(
        server=ConfigServer(
            host=os.environ.get("CORE_HOST", "0.0.0.0"),
            port=int(os.environ.get("CORE_PORT", 8000)),
        ),
        broker = ConfigBroker(
            host=os.environ.get("RABBIT_HOST","localhost"),
            queue_task=os.environ.get("RABBIT_QUEUE_TASKS","tasks"),
            queue_result=os.environ.get("RABBIT_QUEUE_RESULTS", "results"),
            user=os.environ.get("RabbitMQ_USER", "guest"),
            password=os.environ.get("RabbitMQ_PASSWORD", "guest"),
            exchange=os.environ.get("RABBIT_EXCHANGE","default_exchange")
        ),

    )


CONFIG = load_config()

