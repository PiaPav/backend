from dataclasses import dataclass
from pathlib import Path

import yaml


MAX_GRAPH_SEARCH_LIMIT = 100


@dataclass
class RulesConfig:
    max_extraction_file_size: int
    max_extraction_structure_size: int
    max_tool_result_size: int
    max_code_range_lines: int
    default_graph_search_limit: int
    max_graph_search_limit: int


config_path = Path(__file__).resolve().with_name("rules.yml")


def _positive_int(value: object, name: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"tools_rules.{name} must be a positive integer")
    return value


def _graph_limits(default: object, maximum: object) -> tuple[int, int]:
    checked_default = _positive_int(default, "default_graph_search_limit")
    checked_maximum = _positive_int(maximum, "max_graph_search_limit")
    if checked_maximum > MAX_GRAPH_SEARCH_LIMIT:
        raise ValueError(
            f"tools_rules.max_graph_search_limit must not exceed {MAX_GRAPH_SEARCH_LIMIT}"
        )
    if checked_default > checked_maximum:
        raise ValueError("tools_rules.default_graph_search_limit must not exceed max_graph_search_limit")
    return checked_default, checked_maximum


with config_path.open("r", encoding="utf-8") as file:
    yaml_config: dict = yaml.safe_load(file)

_default_graph_search_limit, _max_graph_search_limit = _graph_limits(
    yaml_config.get("tools_rules", {}).get("default_graph_search_limit", 20),
    yaml_config.get("tools_rules", {}).get("max_graph_search_limit", MAX_GRAPH_SEARCH_LIMIT),
)

RULES_CONFIG = RulesConfig(
    max_extraction_file_size=yaml_config.get("tools_rules", {}).get("max_extraction_file_size", 10 ** 4),
    max_extraction_structure_size=yaml_config.get("tools_rules", {}).get("max_extraction_structure_size", 10 ** 3),
    max_tool_result_size=yaml_config.get("tools_rules", {}).get("max_tool_result_size", 65_536),
    max_code_range_lines=_positive_int(
        yaml_config.get("tools_rules", {}).get("max_code_range_lines", 200),
        "max_code_range_lines",
    ),
    default_graph_search_limit=_default_graph_search_limit,
    max_graph_search_limit=_max_graph_search_limit,
)
