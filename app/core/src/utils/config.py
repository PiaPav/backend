import os
from dataclasses import dataclass

from dotenv import load_dotenv

# Загружаем переменные из .env файла
load_dotenv()


@dataclass
class ConfigAuth:
    ACCESS_SECRET_KEY: str
    REFRESH_SECRET_KEY: str
    ALGORITHM: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int
    REFRESH_TOKEN_EXPIRE_DAYS: int


@dataclass
class ConfigServer:
    host: str
    port: int


@dataclass
class ConfigDB:
    host: str
    port: int
    name: str
    user: str
    password: str
    echo: bool


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
class ConfigEmail:
    login: str
    password: str


@dataclass
class ConfigRedis:
    host: str
    port: int
    db: int


@dataclass
class Config:
    auth: ConfigAuth
    server: ConfigServer
    db: ConfigDB
    broker: ConfigBroker
    s3: ConfigS3
    grpc: ConfigGRPC
    email: ConfigEmail
    redis: ConfigRedis


def load_config() -> Config:
    return Config(
        auth=ConfigAuth(
            ACCESS_SECRET_KEY=os.environ["ACCESS_SECRET_KEY"],
            REFRESH_SECRET_KEY=os.environ["REFRESH_SECRET_KEY"],
            ALGORITHM=os.environ.get("ALGORITHM", "HS256"),
            ACCESS_TOKEN_EXPIRE_MINUTES=int(os.environ["ACCESS_TOKEN_EXPIRE_MINUTES"]),
            REFRESH_TOKEN_EXPIRE_DAYS=int(os.environ["REFRESH_TOKEN_EXPIRE_DAYS"]),
        ),
        server=ConfigServer(
            host=os.environ.get("CORE_HOST", "0.0.0.0"),
            port=int(os.environ.get("CORE_PORT", 8000)),
        ),
        db=ConfigDB(
            host=os.environ.get("POSTGRES_HOST", "postgres"),
            port=int(os.environ.get("POSTGRES_PORT", 5432)),
            name=os.environ["POSTGRES_DB"],
            user=os.environ["POSTGRES_USER"],
            password=os.environ["POSTGRES_PASSWORD"],
            echo=os.environ.get("POSTGRES_ECHO", "false").lower() in ["true", "1", "yes", 1]
        ),
        broker=ConfigBroker(
            host=os.environ.get("RABBIT_HOST", "localhost"),
            queue_task=os.environ.get("RABBIT_QUEUE_TASKS", "tasks"),
            queue_result=os.environ.get("RABBIT_QUEUE_RESULTS", "results"),
            user=os.environ.get("RabbitMQ_USER", "guest"),
            password=os.environ.get("RabbitMQ_PASSWORD", "guest"),
            exchange=os.environ.get("RABBIT_EXCHANGE", "default_exchange")
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
        ),
        email=ConfigEmail(
            login=os.environ.get("EMAIL_LOGIN"),
            password=os.environ.get("EMAIL_PASSWORD")
        ),
        redis=ConfigRedis(
            host=os.environ.get("REDIS_HOST", "redis"),
            port=int(os.environ.get("REDIS_PORT", 6379)),
            db=int(os.environ.get("REDIS_DB", 0))
        )
    )


CONFIG = load_config()
