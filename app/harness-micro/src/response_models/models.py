from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class StructureType(StrEnum):
    CLASS = "CLASS"
    FUNCTION = "FUNCTION"
    METHOD = "METHOD"
    CONSTANT = "CONSTANT"


class ToolName(StrEnum):
    Get_Content = "GET-CONTENT"
    Get_Structure = "GET-STRUCTURE"


class DeepseekModels(StrEnum):
    flash = "deepseek-flash"
    pro = "deepseek-v4-pro"


class Role(StrEnum):
    system = "system"
    user = "user"
    assistant = "assistant"
    tool = "tool"


# ---------- Tool calls ----------

class FunctionCall(BaseModel):
    name: str
    arguments: str  # JSON-строка


class ToolCall(BaseModel):
    id: str
    function: FunctionCall
    type: Literal["function"] = "function"


# ---------- Messages ----------

class Prompt(BaseModel):
    role: Role
    content: str | None


class ToolResponse(BaseModel):
    tool_call_id: str
    content: str
    role: Role = Role.tool


# ---------- Tool definitions ----------

class ToolParameterTypes(StrEnum):
    string = "string"
    integer = "integer"
    number = "number"
    boolean = "boolean"
    array = "array"
    object = "object"


class ToolParameter(BaseModel):
    type: ToolParameterTypes
    description: str
    enum: list[Any] | None = None
    items: dict[str, Any] | None = None


class ToolParameters(BaseModel):
    properties: dict[str, ToolParameter]
    required: list[str] = Field(default_factory=list)
    additionalProperties: bool = False
    type: Literal["object"] = "object"


class ToolSubdata(BaseModel):
    name: str
    description: str
    parameters: ToolParameters
    strict: bool | None = None


class ToolData(BaseModel):
    function: ToolSubdata
    type: Literal["function"] = "function"


# ---------- Response ----------

class ModelMessage(BaseModel):
    role: Role
    content: str | None
    tool_calls: list[ToolCall] | None = None
    reasoning_content: str | None = None


class FinishReasonType(StrEnum):
    tool_calls = "tool_calls"
    stop = "stop"
    length = "length"
    content_filter = "content_filter"
    insufficient_system_resource = "insufficient_system_resource"
    aborted = "aborted"


class ModelChoice(BaseModel):
    index: int
    message: ModelMessage
    finish_reason: FinishReasonType


class ModelUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    prompt_cache_hit_tokens: int = 0
    prompt_cache_miss_tokens: int = 0


class ModelResponse(BaseModel):
    id: str
    object: str
    created: int
    model: str
    choices: list[ModelChoice]
    usage: ModelUsage
    system_fingerprint: str | None = None


# ---------- Request ----------

class Request(BaseModel):
    model: DeepseekModels
    messages: list[
        Prompt | ModelMessage | ToolResponse
        ]
    tools: list[ToolData] = Field(default_factory=list)
    tool_choice: Literal[
        "auto", "none", "required"
    ] = "auto"
    stream: bool = False
    reasoning_effort: Literal[
                          "none", "low", "high", "max"
                      ] | None = None
