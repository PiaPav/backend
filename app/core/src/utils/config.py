from dataclasses import dataclass, fields, is_dataclass
from pathlib import Path
from typing import Any, Dict, Type, TypeVar, Optional

from yaml import safe_load

LOCAL_CONFIG_PATH: Path = Path(__file__).parent / "config-local.yml"

T = TypeVar('T')


@dataclass
class ConfigAuth:
    """Конфиг Авторизации"""
    ACCESS_SECRET_KEY: str
    REFRESH_SECRET_KEY: str
    ALGORITHM: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int
    REFRESH_TOKEN_EXPIRE_DAYS: int


@dataclass
class ConfigServer:
    """Конфиг сервера"""
    host: str
    port: int


@dataclass
class ConfigDB:
    """Конфиг базы данных"""
    host: str
    port: int
    name: str
    user: str
    password: str
    echo: Optional[bool] = False


@dataclass
class Config:
    """Глобальный конфиг"""
    auth: ConfigAuth
    server: ConfigServer
    db: ConfigDB


class ConfigLoader:
    """Загрузка конфига из файла"""
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._config = cls._load_config()
        return cls._instance

    @property
    def config(self) -> Config:
        return self._config

    @classmethod
    def _load_config(cls) -> Config:
        config_data = cls._read_config()
        return cls._create_dataclass(Config, config_data)

    @staticmethod
    def _read_config() -> Dict[str, Any]:
        if LOCAL_CONFIG_PATH.exists():
            with open(LOCAL_CONFIG_PATH, "r") as config_file:
                return safe_load(config_file)
        raise FileNotFoundError('Отсутствует конфиг формата "config.yaml"')

    @staticmethod
    def _create_dataclass(cls: Type[T], data: Dict[str, Any]) -> T:
        if not is_dataclass(cls):
            raise ValueError(f"{cls.__name__} не является датаклассом (именем в конфигурации)")

        kwargs = {}
        for field in fields(cls):
            field_name = field.name
            if field_name not in data:
                raise ValueError(f"Пропущено поле '{field_name}' в конфиге для {cls.__name__}")

            field_value = data[field_name]
            field_type = field.type

            if is_dataclass(field_type):
                kwargs[field_name] = ConfigLoader._create_dataclass(field_type, field_value)
            else:
                kwargs[field_name] = field_value

        return cls(**kwargs)


config_loader = ConfigLoader()
CONFIG: Config = config_loader.config
