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

    def create_start_messages(self, graph, metrix) -> list[Prompt]:
        """Создает системный промт и сообщение с графом и метриками"""
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

        content += "\n===GRAPH===\n"
        content += graph
        content += "\n===GRAPH===\n"

        content += "\n===METRIX===\n"
        content += metrix
        content += "\n===METRIX===\n"

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
