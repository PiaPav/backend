from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class RulesConfig:
    max_extraction_file_size: int
    max_extraction_structure_size: int


config_path = Path(__file__).resolve().with_name("rules.yml")

with config_path.open("r", encoding="utf-8") as file:
    yaml_config: dict = yaml.safe_load(file)

RULES_CONFIG = RulesConfig(
    max_extraction_file_size=yaml_config.get("tools_rules", {}).get("max_extraction_file_size", 10 ** 4),
    max_extraction_structure_size=yaml_config.get("tools_rules", {}).get("max_extraction_structure_size", 10 ** 3)
)
