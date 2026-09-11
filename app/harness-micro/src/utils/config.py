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


@dataclass
class Config:
    llm: LLMConfig


def load_config() -> Config:
    """Загрузка конфига"""
    local_config = Path(__file__).parent / "config-local.yml"
    if local_config.is_file():
        print(f"FILE {local_config}")
        with local_config.open("r", encoding="utf-8") as file:
            yaml_config: dict = yaml.safe_load(file)
            print(yaml_config)

        return Config(
            llm=LLMConfig(
                url=yaml_config.get("llm_config").get("url"),
                apikey=yaml_config.get("llm_config").get("apikey"),
                prompts_dir=yaml_config.get("llm_config").get("prompts_dir")
            )
        )

    return Config(
        llm=LLMConfig(
            url=os.environ.get("llm_config").get("url"),
            apikey=os.environ.get("llm_config").get("apikey"),
            prompts_dir=os.environ.get("llm_config").get("prompts_dir")
        )
    )


CONFIG = load_config()
