from llm_connector.interfaces.prompts_loader import PromptsLoaderInterface
from llm_connector.interfaces.validator import ValidatorInterface
from response_models.models import ToolData, Prompt, Role, ToolResponse, ToolCall
from tools_engine.registry import TOOL_REGISTRY, ToolDefinition, validate_registry


class Validator(ValidatorInterface):

    def __init__(self, prompts_loader: PromptsLoaderInterface,
                 registry: tuple[ToolDefinition, ...] = TOOL_REGISTRY):
        self.prompts_loader = prompts_loader
        validate_registry(registry)
        self.registry = registry

    def create_start_messages(
        self, graph_overview: str, metrics_overview: str,
        graph_profile_ids: list[str], metrics_profile_ids: list[str],
        max_tool_calls: int,
    ) -> list[Prompt]:
        """Создаёт prompt только из обзорных профилей и каталогов."""
        prompts: list[Prompt] = []

        instructions = ""

        instructions += self.prompts_loader.load_prompt()
        # instructions += self.prompts_loader.load_commands()

        prompt = Prompt(
            role=Role.system,
            content=instructions
        )
        prompts.append(prompt)

        content = ""

        content += f"\n===TOOL-BUDGET===\n{max_tool_calls}\n===TOOL-BUDGET===\n"
        content += "\n===GRAPH-PROFILES===\n" + "\n".join(graph_profile_ids) + "\n===GRAPH-PROFILES===\n"
        content += "\n===METRICS-PROFILES===\n" + "\n".join(metrics_profile_ids) + "\n===METRICS-PROFILES===\n"
        content += "\n===AGGREGATE-OVERVIEW===\n" + graph_overview + "\n===AGGREGATE-OVERVIEW===\n"
        content += "\n===METRICS-OVERVIEW===\n" + metrics_overview + "\n===METRICS-OVERVIEW===\n"
        content += ("\nОбзорные профили могут быть неполными или усечёнными: учитывай их признаки "
                    "completeness и не считай отсутствие элемента доказательством отсутствия в полном профиле. "
                    "Полные профили доступны только через инструменты.\n")

        prompt = Prompt(
            role=Role.system,
            content=content
        )
        prompts.append(prompt)

        return prompts

    def load_tools_models(self) -> list[ToolData]:
        tools = []
        for definition in self.registry:
            tool_json_data = definition.schema_path.read_text(encoding="utf-8")
            tool_data = ToolData.model_validate_json(tool_json_data)
            tools.append(tool_data)

        return tools

    def create_tool_message(self, tool_call: ToolCall, content: str) -> ToolResponse:
        """Создает сообщения с информацией из тулы для нейронки"""
        message = ToolResponse(
            tool_call_id=tool_call.id,
            content=content,
        )
        return message

    def create_message(self, msg: str) -> Prompt:
        """Создает сообщение с текстом"""
        message = Prompt(
            role=Role.system,
            content=msg
        )

        return message
