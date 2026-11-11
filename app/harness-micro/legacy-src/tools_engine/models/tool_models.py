from dataclasses import dataclass
from enum import StrEnum


class ToolName(StrEnum):
    Get_Content = "GET-CONTENT"
    Get_Structure = "GET-STRUCTURE"


@dataclass
class ExecuteToolData:
    name: ToolName
    context: dict


class StructureType(StrEnum):
    CLASS = "CLASS"
    FUNCTION = "FUNCTION"
    METHOD = "METHOD"
    CONSTANT = "CONSTANT"


@dataclass
class LLMResponse:
    use_tool: bool
    tool_name: ToolName | None
    tool_data: dict | None
    message: str
