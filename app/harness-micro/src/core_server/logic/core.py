import time
from pathlib import Path

from core_server.interfaces.core import CoreInterface
from core_server.models.task_models import HarnessInputData, TaskStatus, TaskInfo
from llm_connector.interfaces.connector import LLMConnectorInterface
from llm_connector.interfaces.validator import ValidatorInterface
from response_models.models import FinishReasonType, ToolCall
from tools_engine.interface.engine import EngineInterface

# TODO Вынести в конфиг?
TASK_EXPIRED_TIME_MIN = 60
COUNT_MESSAGES = 3


class Core(CoreInterface):

    def __init__(self, llm_connector: LLMConnectorInterface, tools_engine: EngineInterface,
                 validator: ValidatorInterface):
        self.tasks: dict[int, TaskInfo] = {}
        self.exp_span: int = TASK_EXPIRED_TIME_MIN * 60
        self.llm_connector: LLMConnectorInterface = llm_connector
        self.tools_engine: EngineInterface = tools_engine
        self.message_validator: ValidatorInterface = validator

    async def start(self, url, apikey):
        """Запустить систему"""
        await self.llm_connector.connect(url, apikey)
        self.tools_engine.start()

    def _clear_old_tasks(self):
        """Удалить устаревшие задачи"""
        current_time = time.time()
        for task_id in self.tasks:
            if (self.tasks[task_id].expire_time < current_time and
                    self.tasks[task_id].status == TaskStatus.done):
                self.tasks.pop(task_id)
            else:
                break

    def _load_file(self, path: Path) -> str:
        """Загрузчик файлов (в будущем мб перекатить на редис)"""
        return path.read_text(encoding="utf-8")

    async def _llm_loop(self, unique_id: int, graph: str, metrix: str, index: Path) -> str:
        """Цикл общения с нейронкой"""
        session = await self.llm_connector.create_session(unique_id)

        messages = self.message_validator.create_start_messages(graph, metrix)

        tools = self.message_validator.load_tools_models()

        answer = await session.send_start(messages=messages, tools=tools)

        self.tasks[unique_id].current_iteration += 1

        # Цикл запрос-ответ
        while self.tasks[unique_id].current_iteration <= COUNT_MESSAGES:
            # valid_anwer = self.message_validator.validate_response(answer)
            choice = answer.choices[0]

            if choice.finish_reason == FinishReasonType.stop:
                return choice.message.content

            if choice.finish_reason == FinishReasonType.tool_calls:
                tool_calls: list[ToolCall] = choice.message.tool_calls

                tool_messages = []

                for tool_call in tool_calls:
                    function = tool_call.function
                    additional_data = self.tools_engine.entry_tool(
                        source_index_path=index,
                        name=function.name,
                        arguments=function.arguments
                    )

                    message = self.message_validator.create_tool_message(
                        tool_call=tool_call,
                        data=additional_data
                    )

                    tool_messages.append(message)

                answer = await session.send(messages=tool_messages)

            else:
                # TODO Обработка ошибок
                pass

            self.tasks[unique_id].current_iteration += 1

        raise

        # TODO Что делать если цикл кончился, а результата не было??

    async def run_task(self, data: HarnessInputData) -> str:
        """Передать задачу ллм"""
        self.tasks[data.unique_id] = TaskInfo(
            unique_id=data.unique_id,
            current_iteration=0,
            expire_time=time.time() + self.exp_span,
            status=TaskStatus.accept
        )

        graph = self._load_file(data.graph_path)
        metrix = self._load_file(data.metrics_path)

        result = await self._llm_loop(data.unique_id, graph, metrix, data.source_index_path)

        return result
