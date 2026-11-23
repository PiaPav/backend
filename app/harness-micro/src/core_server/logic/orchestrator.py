import asyncio
import json
import time
from pathlib import Path

from core_server.interfaces.orchestrator import OrchestratorInterface
from core_server.interfaces.errors import HarnessError, InvalidHarnessInput
from core_server.models.task_models import HarnessInputData, TaskInfo, TaskStatus
from llm_connector.interfaces.connector import LLMConnectorInterface
from llm_connector.interfaces.validator import ValidatorInterface
from response_models.models import FinishReasonType, LLMAnalysis, ToolCall
from tools_engine.interface.engine import EngineInterface
from tools_engine.interface.tool import ToolError
from tools_engine.models.analysis_context import AnalysisContext
from tools_engine.models.tool_result import ToolResult
from utils.logger import create_logger

TASK_EXPIRED_TIME_MIN = 60 * 60


class GenerationLengthExceeded(HarnessError):
    pass


class ContentFilterTriggered(HarnessError):
    pass


class ProviderUnavailable(HarnessError):
    pass


class GenerationAborted(HarnessError):
    pass


class FinalAnswerAbsent(HarnessError):
    pass


log = create_logger("Orchestrator")


class Orchestrator(OrchestratorInterface):
    def __init__(
        self, llm_connector: LLMConnectorInterface, tools_engine: EngineInterface,
        validator: ValidatorInterface, *, max_tool_calls: int,
        max_iterations: int, max_start_context_size: int, max_provider_retries: int,
    ):
        self.tasks: dict[int, TaskInfo] = {}
        self.llm_connector = llm_connector
        self.tools_engine = tools_engine
        self.message_validator = validator
        self.max_tool_calls = max_tool_calls
        self.max_iterations = max_iterations
        self.max_start_context_size = max_start_context_size
        self.max_provider_retries = max_provider_retries

    async def start(self, url, apikey):
        await self.llm_connector.connect(url, apikey)
        self.tools_engine.start()

    def _clear_old_tasks(self):
        current_time = self._now()
        for task_id in list(self.tasks):
            task = self.tasks[task_id]
            if task.expire_time < current_time and task.status == TaskStatus.done:
                self.tasks.pop(task_id)

    @staticmethod
    def _load_file(path: Path) -> str:
        return path.read_text(encoding="utf-8")

    @staticmethod
    def _now() -> float:
        return time.perf_counter()

    @staticmethod
    def _tool_log_metadata(tool_name: str, result: ToolResult) -> str:
        return json.dumps({
            "tool_name": tool_name, "status": result.status,
            "profile_id": result.profile_id,
            "completeness": {
                "returned": result.completeness.returned,
                "total": result.completeness.total,
                "truncated": result.completeness.truncated,
            },
            "serialized_utf8_size": result.utf8_size(),
        }, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _answer_log_metadata(answer) -> str:
        choice = answer.choices[0]
        calls = choice.message.tool_calls or []
        finish_reason = choice.finish_reason
        return json.dumps({
            "finish_reason": (finish_reason.value
                              if isinstance(finish_reason, FinishReasonType)
                              else finish_reason),
            "tool_call_count": len(calls),
            "tool_names": [call.function.name for call in calls],
        }, ensure_ascii=False, separators=(",", ":"))

    async def _retry_provider(self, session, answer):
        delay = 2
        retries = 0
        while (answer.choices[0].finish_reason
               == FinishReasonType.insufficient_system_resource
               and retries < self.max_provider_retries):
            await asyncio.sleep(delay)
            answer = await session.retry_send()
            retries += 1
            delay = min(delay * 2, 32)
        if answer.choices[0].finish_reason == FinishReasonType.insufficient_system_resource:
            raise ProviderUnavailable("Провайдер перегружен, попробуй перезапустить позже", answer.model_dump())
        return answer

    def _raise_terminal_error(self, answer) -> None:
        reason = answer.choices[0].finish_reason
        if reason == FinishReasonType.length:
            raise GenerationLengthExceeded(
                "Генерация ответа остановлена из-за лимита токенов / контекстного окна",
                answer.model_dump(),
            )
        if reason == FinishReasonType.content_filter:
            raise ContentFilterTriggered(
                "Сработал фильтр, продолжать обработку запроса невозможно", answer.model_dump()
            )
        if reason == FinishReasonType.aborted:
            raise GenerationAborted("Генерация прервана, попробуй перезапустить позже", answer.model_dump())
        raise HarnessError("Неизвестная причина завершения генерации", answer.model_dump())

    def _limit_result(self, task: TaskInfo) -> ToolResult:
        return ToolResult.failure(ToolError(
            f"Исчерпан лимит использования инструментов. Использовано "
            f"{task.count_tool_calls} из {self.max_tool_calls}.",
            {"limit": self.max_tool_calls, "used": task.count_tool_calls},
            False, code="tool_call_limit_exceeded",
        ))

    async def _execute_calls(
        self, unique_id: int, calls: list[ToolCall], analysis_context: AnalysisContext,
    ) -> list:
        task = self.tasks[unique_id]
        messages = []
        for call in calls:
            if task.count_tool_calls >= self.max_tool_calls:
                result = self._limit_result(task)
            else:
                # Бюджет считается после принятия call и до внешнего исполнения.
                task.count_tool_calls += 1
                result = await self.tools_engine.entry_tool(
                    analysis_context=analysis_context,
                    name=call.function.name,
                    arguments=call.function.arguments,
                )
            messages.append(self.message_validator.create_tool_message(call, result.to_json()))
            log.info(unique_id=unique_id, event="Обработан вызов инструмента",
                     description=self._tool_log_metadata(call.function.name, result))
        return messages

    async def run_loop(
        self, unique_id: int, graph_overview: str, metrics_overview: str,
        analysis_context: AnalysisContext,
    ) -> str:
        task = self.tasks[unique_id]
        messages = self.message_validator.create_start_messages(
            graph_overview, metrics_overview,
            sorted(analysis_context.graph_profiles),
            sorted(analysis_context.metrics_profiles),
            self.max_tool_calls,
        )
        start_size = sum(len((message.content or "").encode("utf-8")) for message in messages)
        if start_size > self.max_start_context_size:
            raise InvalidHarnessInput(
                "Стартовый контекст превышает допустимый размер",
                {"actual_size": start_size, "limit": self.max_start_context_size},
            )

        session = await self.llm_connector.create_session(unique_id)
        try:
            answer = await self._retry_provider(
                session,
                await session.send_start(messages=messages, tools=self.message_validator.load_tools_models()),
            )
            while True:
                task.current_iteration += 1
                choice = answer.choices[0]
                log.info(unique_id=unique_id, event="Получен ответ LLM",
                         description=self._answer_log_metadata(answer))

                if choice.finish_reason == FinishReasonType.stop:
                    if task.count_tool_calls == 0 and task.current_iteration < self.max_iterations:
                        prompt = self.message_validator.create_message(
                            "Перед финальным ответом подтверди гипотезы с помощью инструментов."
                        )
                        answer = await self._retry_provider(session, await session.send(messages=[prompt]))
                        continue
                    return await self._finalize(session, unique_id)

                if choice.finish_reason != FinishReasonType.tool_calls:
                    self._raise_terminal_error(answer)

                if not choice.message.tool_calls:
                    return await self._finalize(session, unique_id)

                tool_messages = await self._execute_calls(
                    unique_id, choice.message.tool_calls or [], analysis_context
                )
                if (task.count_tool_calls >= self.max_tool_calls
                        or task.current_iteration >= self.max_iterations):
                    return await self._finalize(session, unique_id, tool_messages)

                answer = await self._retry_provider(session, await session.send(messages=tool_messages))
        finally:
            await self.llm_connector.close_session(unique_id)

    async def run_task(self, data: HarnessInputData) -> str:
        self._clear_old_tasks()
        task = TaskInfo(
            unique_id=data.unique_id, current_iteration=0,
            expire_time=self._now() + TASK_EXPIRED_TIME_MIN,
            status=TaskStatus.accept, count_tool_calls=0,
        )
        self.tasks[data.unique_id] = task
        try:
            context = AnalysisContext(
                task_id=data.unique_id, graph_profiles=data.graph_profiles,
                metrics_profiles=data.metrics_profiles,
                source_index_path=data.source_index_path,
                graph_fingerprint=data.graph_fingerprint,
                project_fingerprint=data.project_fingerprint,
            )
            if "aggregate.overview" not in context.graph_profiles:
                raise InvalidHarnessInput("Отсутствует обязательный профиль aggregate.overview")
            if "metrics.overview" not in context.metrics_profiles:
                raise InvalidHarnessInput("Отсутствует обязательный профиль metrics.overview")
            graph = self._load_file(context.graph_profiles["aggregate.overview"])
            metrics = self._load_file(context.metrics_profiles["metrics.overview"])
            task.status = TaskStatus.in_processing
            return await self.run_loop(data.unique_id, graph, metrics, context)
        finally:
            task.status = TaskStatus.done
            await log.flush_async()

    async def _finalize(self, session, unique_id: int, prior_messages: list | None = None) -> str:
        prompt = self.message_validator.create_message(
            "Анализ завершён. Сформируй итоговый отчёт в соответствии с JSON-контрактом. "
            "Используй только полученные данные. Не вызывай инструменты. Верни исключительно JSON."
        )
        answer = await self._retry_provider(
            session, await session.final_send(messages=[*(prior_messages or []), prompt])
        )
        choice = answer.choices[0]
        if choice.finish_reason != FinishReasonType.stop:
            raise FinalAnswerAbsent("Не удалось получить финальный JSON", answer.model_dump())
        content = choice.message.content
        if not content or not content.strip():
            raise FinalAnswerAbsent("LLM вернула пустой JSON-ответ", answer.model_dump())
        return LLMAnalysis.model_validate_json(content).model_dump_json()
