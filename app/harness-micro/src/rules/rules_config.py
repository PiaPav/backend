from dataclasses import dataclass
from pathlib import Path

import yaml


MAX_GRAPH_SEARCH_LIMIT = 100
MAX_GRAPH_DEPTH = 10
MAX_GRAPH_ITEM_LIMIT = 1000
MAX_TOOL_CALLS_CEILING = 6
MAX_PROVIDER_RETRIES_CEILING = 10


@dataclass
class RulesConfig:
    max_extraction_file_size: int
    max_extraction_structure_size: int
    max_tool_result_size: int
    max_code_range_lines: int
    default_graph_search_limit: int
    max_graph_search_limit: int
    max_graph_subgraph_depth: int
    max_graph_subgraph_nodes: int
    max_graph_references_limit: int
    max_tool_calls: int
    max_iterations: int
    max_start_context_size: int
    max_provider_retries: int

    def __post_init__(self) -> None:
        _positive_int(self.max_tool_calls, "max_tool_calls")
        _positive_int(self.max_iterations, "max_iterations")
        _positive_int(self.max_start_context_size, "max_start_context_size")
        _nonnegative_int(self.max_provider_retries, "max_provider_retries")
        if self.max_tool_calls > MAX_TOOL_CALLS_CEILING:
            raise ValueError(
                f"harness_rules.max_tool_calls must not exceed {MAX_TOOL_CALLS_CEILING}"
            )
        if self.max_provider_retries > MAX_PROVIDER_RETRIES_CEILING:
            raise ValueError(
                f"harness_rules.max_provider_retries must not exceed {MAX_PROVIDER_RETRIES_CEILING}"
            )


config_path = Path(__file__).resolve().with_name("rules.yml")


def _positive_int(value: object, name: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"tools_rules.{name} must be a positive integer")
    return value


def _nonnegative_int(value: object, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"harness_rules.{name} must be a nonnegative integer")
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
    max_graph_subgraph_depth=_positive_int(
        yaml_config.get("tools_rules", {}).get("max_graph_subgraph_depth", 5),
        "max_graph_subgraph_depth",
    ),
    max_graph_subgraph_nodes=_positive_int(
        yaml_config.get("tools_rules", {}).get("max_graph_subgraph_nodes", 100),
        "max_graph_subgraph_nodes",
    ),
    max_graph_references_limit=_positive_int(
        yaml_config.get("tools_rules", {}).get("max_graph_references_limit", 100),
        "max_graph_references_limit",
    ),
    max_tool_calls=_positive_int(
        yaml_config.get("harness_rules", {}).get("max_tool_calls", 6),
        "max_tool_calls",
    ),
    max_iterations=_positive_int(
        yaml_config.get("harness_rules", {}).get("max_iterations", 8),
        "max_iterations",
    ),
    max_start_context_size=_positive_int(
        yaml_config.get("harness_rules", {}).get("max_start_context_size", 262_144),
        "max_start_context_size",
    ),
    max_provider_retries=_nonnegative_int(
        yaml_config.get("harness_rules", {}).get("max_provider_retries", 4),
        "max_provider_retries",
    ),
)

if RULES_CONFIG.max_graph_subgraph_depth > MAX_GRAPH_DEPTH:
    raise ValueError("tools_rules.max_graph_subgraph_depth exceeds hard ceiling")
if (RULES_CONFIG.max_graph_subgraph_nodes > MAX_GRAPH_ITEM_LIMIT
        or RULES_CONFIG.max_graph_references_limit > MAX_GRAPH_ITEM_LIMIT):
    raise ValueError("graph item limit exceeds hard ceiling")
if RULES_CONFIG.max_tool_calls > MAX_TOOL_CALLS_CEILING:
    raise ValueError(
        f"harness_rules.max_tool_calls must not exceed {MAX_TOOL_CALLS_CEILING}"
    )
