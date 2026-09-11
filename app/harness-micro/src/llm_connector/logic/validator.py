from llm_connector.interfaces.connector import Message, MessageAuthors
from llm_connector.interfaces.prompts_loader import PromptsLoaderInterface
from llm_connector.interfaces.validator import ValidatorInterface
from tools_engine.models.tool_models import ToolName, LLMResponse, ExecuteToolData

COMMAND_CONTEXT_FROM_NAME = {
    ToolName.Get_Content: ["FILEPATH"],
    ToolName.Get_Structure: ["FILEPATH", "STRUCTURE-TYPE", "STRUCTURE-PATH"]
}  # Контекст сохраняем в str виде, тула сама приведет в нужный формат


class Validator(ValidatorInterface):

    def __init__(self, prompts_loader: PromptsLoaderInterface):
        self.prompts_loader = prompts_loader

    def create_message(self, graph, metrix) -> Message:
        """Создает и валидирует сообщение"""
        instructions = ""

        instructions += self.prompts_loader.load_prompt()
        instructions += self.prompts_loader.load_commands()

        content = ""

        content += "\n===GRAPH===\n"
        content += graph
        content += "\n===GRAPH===\n"

        content += "\n===METRIX===\n"
        content += metrix
        content += "\n===METRIX===\n"

        message = Message(
            author=MessageAuthors.user,
            instructions=instructions,
            content=content
        )

        return message

    def _validate_command(self, command: str) -> ExecuteToolData:
        """Валидирует команду от нейронки"""
        split_command = command.split()
        command_name = ToolName(split_command[0])
        list_args = COMMAND_CONTEXT_FROM_NAME[command_name]
        command_context = dict(zip(list_args, split_command[1:]))

        return ExecuteToolData(
            name=command_name,
            context=command_context
        )

    def validate_response(self, data: str) -> LLMResponse:
        """Валидирует ответ нейронки"""
        response_type, separator, message = data.partition("\n")

        if response_type == "tool":
            raw_command = message
            command = self._validate_command(raw_command)
            return LLMResponse(
                use_tool=True,
                tool_name=command.name,
                tool_data=command.context,
                message=""
            )
        if response_type == "result":
            return LLMResponse(
                use_tool=False,
                tool_name=None,
                tool_data=None,
                message=message
            )
        else:
            raise  # Ошибка - непредвиденный тип сообщения

    def create_tool_message(self, tool_name: ToolName, data: str) -> Message:
        """Создает сообщения с информацией из тулы для нейронки"""
        instructions = self.prompts_loader.load_tool(tool_name)

        message = Message(
            author=MessageAuthors.user,
            instructions=instructions,
            content=data
        )

        return message
