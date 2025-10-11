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
class Config:
    auth: ConfigAuth
    server: ConfigServer
    db: ConfigDB


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
            echo=bool(int(os.environ["POSTGRES_ECHO"]))
        ),
    )


CONFIG = load_config()
