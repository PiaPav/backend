import asyncio
import json
from typing import Any

from response_models.models import ToolData, ToolName, ToolParameterTypes
from rules.rules_config import RULES_CONFIG
from tools_engine.interface.engine import EngineInterface
from tools_engine.interface.tool import (
    ExtractionLimitExceeded, InvalidArtifact, InvalidToolArguments, ToolError, UnknownTool,
)
from tools_engine.models.analysis_context import AnalysisContext
from tools_engine.models.tool_result import ToolResult
from tools_engine.registry import TOOL_REGISTRY, ToolDefinition, validate_registry


class ToolsEngine(EngineInterface):
    def __init__(self, registry: tuple[ToolDefinition, ...] = TOOL_REGISTRY):
        validate_registry(registry)
        self.registry = registry
        self.registered_tools = {
            definition.name: definition.implementation() for definition in registry
        }
        self._schemas = {
            definition.name: ToolData.model_validate_json(
                definition.schema_path.read_text(encoding="utf-8")
            )
            for definition in registry
        }

    def start(self):
        pass

    @staticmethod
    def _validate(arguments: Any, schema: ToolData) -> dict[str, Any]:
        if not isinstance(arguments, dict):
            raise InvalidToolArguments("Аргументы инструмента должны быть JSON-объектом")
        parameters = schema.function.parameters
        missing = [name for name in parameters.required if name not in arguments]
        if missing:
            raise InvalidToolArguments("Отсутствуют обязательные аргументы", {"missing": missing})
        extras = sorted(set(arguments) - set(parameters.properties))
        if extras and not parameters.additionalProperties:
            raise InvalidToolArguments("Переданы неизвестные аргументы", {"additional": extras})
        python_types = {
            ToolParameterTypes.string: str, ToolParameterTypes.integer: int,
            ToolParameterTypes.number: (int, float), ToolParameterTypes.boolean: bool,
            ToolParameterTypes.array: list, ToolParameterTypes.object: dict,
        }
        for name, value in arguments.items():
            parameter = parameters.properties.get(name)
            if parameter is None:
                continue
            expected = python_types[parameter.type]
            valid = isinstance(value, expected)
            if parameter.type in (ToolParameterTypes.integer, ToolParameterTypes.number) and isinstance(value, bool):
                valid = False
            if not valid:
                raise InvalidToolArguments("Неверный тип аргумента", {"argument": name, "expected": parameter.type.value})
            if parameter.enum is not None and value not in parameter.enum:
                raise InvalidToolArguments("Недопустимое значение аргумента", {"argument": name, "allowed": parameter.enum})
        return arguments

    async def entry_tool(self, analysis_context: AnalysisContext, name: str, arguments: str) -> ToolResult:
        try:
            try:
                tool_name = ToolName(name)
            except ValueError as exc:
                raise UnknownTool(details={"tool": name}) from exc
            tool = self.registered_tools.get(tool_name)
            if tool is None:
                raise UnknownTool(details={"tool": name})
            try:
                raw_arguments = json.loads(arguments)
            except (json.JSONDecodeError, TypeError) as exc:
                raise InvalidToolArguments("Аргументы не соответствуют формату JSON") from exc
            context = self._validate(raw_arguments, self._schemas[tool_name])
            result = await asyncio.to_thread(tool.execute, analysis_context, **context)
            tool_result = ToolResult.success(result)
        except ToolError as exc:
            tool_result = ToolResult.failure(exc)
        except Exception:
            tool_result = ToolResult.failure(InvalidArtifact(
                "Не удалось безопасно обработать артефакт", {"artifact": "tool_input"}
            ))

        actual_size = tool_result.utf8_size()
        limit = RULES_CONFIG.max_tool_result_size
        if actual_size > limit:
            fallback = ToolResult.failure(ExtractionLimitExceeded(details={
                "scope": "serialized_tool_result",
                "limit_bytes": limit,
                "actual_bytes": actual_size,
            }))
            if fallback.utf8_size() <= limit:
                return fallback
            # A valid ToolResult envelope itself may be larger than a pathological
            # configured limit. Never return the original, potentially untrusted value.
            return ToolResult.failure(ExtractionLimitExceeded("E", {}))
        return tool_result
