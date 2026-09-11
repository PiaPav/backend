import time
from pathlib import Path

from core_server.interfaces.core import CoreInterface
from core_server.models.task_models import HarnessInputData, TaskStatus, TaskInfo
from llm_connector.interfaces.connector import LLMConnectorInterface
from llm_connector.interfaces.validator import ValidatorInterface
from tools_engine.interface.engine import EngineInterface
from tools_engine.models.tool_models import ExecuteToolData

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

    def start(self, url, apikey):
        """Запустить систему"""
        self.llm_connector.connect(url, apikey)
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
        pass

    async def _llm_loop(self, unique_id: int, graph: str, metrix: str, index: Path) -> str:
        """Цикл общения с нейронкой"""
        session = await self.llm_connector.create_session(unique_id)

        message = self.message_validator.create_message(graph, metrix)

        answer = await session.send(message)

        self.tasks[unique_id].current_iteration += 1

        # Цикл запрос-ответ
        while self.tasks[unique_id].current_iteration <= COUNT_MESSAGES:
            valid_anwer = self.message_validator.validate_response(answer)
            if valid_anwer.use_tool:
                additional_data: str = self.tools_engine.entry_tool(
                    source_index_path=index,
                    data=ExecuteToolData(
                        name=valid_anwer.tool_name,
                        context=valid_anwer.tool_data
                    ))
                message = self.message_validator.create_tool_message(
                    tool_name=valid_anwer.tool_name,
                    data=additional_data
                )
            else:
                return valid_anwer.message

            await session.send(message)

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
