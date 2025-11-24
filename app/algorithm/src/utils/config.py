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
class ConfigS3:
    host: str
    port: int
    port_console: int
    ACCESS_ID: str
    SECRET_KEY: str
    BUCKET: str

@dataclass
class ConfigGRPC:
    host: str
    port: int

@dataclass
class Config:
    server: ConfigServer
    broker: ConfigBroker
    s3: ConfigS3
    grpc: ConfigGRPC


def load_config() -> Config:
    return Config(
        server=ConfigServer(
            host=os.environ.get("HOST", "0.0.0.0"),
            port=int(os.environ.get("PORT", 8001)),
        ),
        broker = ConfigBroker(
            host=os.environ.get("RABBIT_HOST","localhost"),
            queue_task=os.environ.get("RABBIT_QUEUE_TASKS","tasks"),
            queue_result=os.environ.get("RABBIT_QUEUE_RESULTS", "results"),
            user=os.environ.get("RabbitMQ_USER", "guest"),
            password=os.environ.get("RabbitMQ_PASSWORD", "guest"),
            exchange=os.environ.get("RABBIT_EXCHANGE","default_exchange")
        ),
        s3=ConfigS3(
            host=os.environ.get("MINIO_HOST", "minio"),
            port=os.environ.get("S3_API_PORT", 9000),
            port_console=os.environ.get("S3_CONSOLE_PORT", 9001),
            ACCESS_ID=os.environ.get("ACCESS_ID", "admin"),
            SECRET_KEY=os.environ.get("SECRET_KEY", "123456789"),
            BUCKET=os.environ.get("BUCKET", "default")
        ),
        grpc=ConfigGRPC(
            host=os.environ.get("GRPC_HOST", "0.0.0.0"),
            port=os.environ.get("GRPC_PORT", 50051)
        )
    )


CONFIG = load_config()

