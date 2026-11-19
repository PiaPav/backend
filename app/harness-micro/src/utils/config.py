import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

# Загружаем переменные из .env файла
load_dotenv()


@dataclass
class LLMConfig:
    url: str
    apikey: str
    prompts_dir: str
    model: str


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
    llm: LLMConfig
    db: ConfigDB


def load_config() -> Config:
    """Загрузка конфига"""
    local_config = Path(__file__).parent / "config-local.yml"
    if local_config.is_file():
        # print(f"FILE {local_config}")
        with local_config.open("r", encoding="utf-8") as file:
            yaml_config: dict = yaml.safe_load(file)
            # print(yaml_config)

        return Config(
            llm=LLMConfig(
                url=yaml_config.get("llm_config").get("url"),
                apikey=yaml_config.get("llm_config").get("apikey"),
                prompts_dir=yaml_config.get("llm_config").get("prompts_dir"),
                model=yaml_config.get("llm_config").get("model")
            ),
            db=ConfigDB(
                host=yaml_config.get("db").get("POSTGRES_HOST", "postgres"),
                port=int(yaml_config.get("db").get("POSTGRES_PORT", 5432)),
                name=yaml_config.get("db").get("POSTGRES_DB"),
                user=yaml_config.get("db").get("POSTGRES_USER"),
                password=yaml_config.get("db").get("POSTGRES_PASSWORD"),
                echo=yaml_config.get("db").get("POSTGRES_ECHO", "false").lower() in ["true", "1", "yes", 1]
            ),
        )

    return Config(
        llm=LLMConfig(
            url=os.environ.get("url"),
            apikey=os.environ.get("apikey"),
            prompts_dir=os.environ.get("prompts_dir"),
            model=os.environ.get("model")
        ),
        db=ConfigDB(
            host=os.environ.get("POSTGRES_HOST", "postgres"),
            port=int(os.environ.get("POSTGRES_PORT", 5432)),
            name=os.environ["POSTGRES_DB"],
            user=os.environ["POSTGRES_USER"],
            password=os.environ["POSTGRES_PASSWORD"],
            echo=os.environ.get("POSTGRES_ECHO", "false").lower() in ["true", "1", "yes", 1]
        ),
    )


CONFIG = load_config()
