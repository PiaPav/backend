from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class RulesConfig:
    max_extraction_file_size: int
    max_extraction_structure_size: int
    max_tool_result_size: int
    max_code_range_lines: int


config_path = Path(__file__).resolve().with_name("rules.yml")


def _positive_int(value: object, name: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"tools_rules.{name} must be a positive integer")
    return value


with config_path.open("r", encoding="utf-8") as file:
    yaml_config: dict = yaml.safe_load(file)

RULES_CONFIG = RulesConfig(
    max_extraction_file_size=yaml_config.get("tools_rules", {}).get("max_extraction_file_size", 10 ** 4),
    max_extraction_structure_size=yaml_config.get("tools_rules", {}).get("max_extraction_structure_size", 10 ** 3),
    max_tool_result_size=yaml_config.get("tools_rules", {}).get("max_tool_result_size", 65_536),
    max_code_range_lines=_positive_int(
        yaml_config.get("tools_rules", {}).get("max_code_range_lines", 200),
        "max_code_range_lines",
    ),
)
