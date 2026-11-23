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
        metadata = {
            "tool_name": tool_name, "status": result.status,
            "profile_id": result.profile_id,
            "completeness": {
                "returned": result.completeness.returned,
                "total": result.completeness.total,
                "truncated": result.completeness.truncated,
            },
            "serialized_utf8_size": result.utf8_size(),
        }
        if result.diagnostics:
            metadata["diagnostics"] = [
                {"code": diagnostic.code, "retryable": diagnostic.retryable}
                for diagnostic in result.diagnostics
            ]
        return json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _answer_log_metadata(answer, **additional_metadata) -> str:
        choice = answer.choices[0]
        calls = choice.message.tool_calls or []
        finish_reason = choice.finish_reason
        metadata = {
            "finish_reason": (finish_reason.value
                              if isinstance(finish_reason, FinishReasonType)
                              else finish_reason),
            "tool_call_count": len(calls),
            "tool_names": [call.function.name for call in calls],
        }
        for field in ("model", "id"):
            value = getattr(answer, field, None)
            if value is not None:
                metadata[field] = value

        usage = getattr(answer, "usage", None)
        usage_metadata = {}
        for field in (
            "prompt_tokens", "completion_tokens", "total_tokens",
            "prompt_cache_hit_tokens", "prompt_cache_miss_tokens",
        ):
            value = (usage.get(field) if isinstance(usage, dict)
                     else getattr(usage, field, None))
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                usage_metadata[field] = value
        if usage_metadata:
            metadata["usage"] = usage_metadata

        metadata.update(additional_metadata)

        return json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))

    async def _retry_provider(self, session, answer, unique_id: int, phase: str):
        delay = 2
        retries = 0
        while (answer.choices[0].finish_reason
               == FinishReasonType.insufficient_system_resource
               and retries < self.max_provider_retries):
            log.warning(unique_id=unique_id, event="Повтор запроса к провайдеру",
                        description=self._answer_log_metadata(
                            answer, phase=phase, attempt=retries + 1))
            await asyncio.sleep(delay)
            answer = await session.retry_send()
            retries += 1
            delay = min(delay * 2, 32)
        if answer.choices[0].finish_reason == FinishReasonType.insufficient_system_resource:
            log.error(unique_id=unique_id, event="Исчерпаны повторы запроса к провайдеру",
                      description=self._answer_log_metadata(
                          answer, phase=phase, attempts=retries))
            raise ProviderUnavailable("Провайдер перегружен, попробуй перезапустить позже", answer.model_dump())
        return answer

    def _raise_terminal_error(self, answer, unique_id: int, phase: str) -> None:
        reason = answer.choices[0].finish_reason
        metadata = self._answer_log_metadata(answer, phase=phase)
        if reason == FinishReasonType.length:
            log.error(unique_id=unique_id, event="Превышен лимит генерации", description=metadata)
            raise GenerationLengthExceeded(
                "Генерация ответа остановлена из-за лимита токенов / контекстного окна",
                answer.model_dump(),
            )
        if reason == FinishReasonType.content_filter:
            log.error(unique_id=unique_id, event="Сработал фильтр содержимого", description=metadata)
            raise ContentFilterTriggered(
                "Сработал фильтр, продолжать обработку запроса невозможно", answer.model_dump()
            )
        if reason == FinishReasonType.aborted:
            log.warning(unique_id=unique_id, event="Генерация прервана", description=metadata)
            raise GenerationAborted("Генерация прервана, попробуй перезапустить позже", answer.model_dump())
        log.error(unique_id=unique_id, event="Неизвестная причина завершения генерации",
                  description=metadata)
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
            log_method = log.info if result.status == "success" else log.warning
            log_method(unique_id=unique_id, event="Обработан вызов инструмента",
                       description=self._tool_log_metadata(call.function.name, result))
        return messages

    async def run_loop(
        self, unique_id: int, graph_overview: str, metrics_overview: str,
        analysis_context: AnalysisContext,
    ) -> str:
        task = self.tasks[unique_id]
        log.info(unique_id=unique_id, event="Начат обмен с LLM",
                 description=json.dumps({"phase": "analysis"}, separators=(",", ":")))
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
                unique_id, "analysis",
            )
            while True:
                task.current_iteration += 1
                choice = answer.choices[0]
                if choice.finish_reason == FinishReasonType.stop:
                    if task.count_tool_calls == 0 and task.current_iteration < self.max_iterations:
                        log.warning(unique_id=unique_id, event="Преждевременная остановка анализа",
                                    description=self._answer_log_metadata(answer))
                        prompt = self.message_validator.create_message(
                            "Перед финальным ответом подтверди гипотезы с помощью инструментов."
                        )
                        answer = await self._retry_provider(
                            session, await session.send(messages=[prompt]), unique_id, "analysis"
                        )
                        continue
                    if (task.count_tool_calls == 0
                            and task.current_iteration >= self.max_iterations):
                        log.warning(unique_id=unique_id, event="Достигнут лимит итераций",
                                    description=json.dumps({"used": task.current_iteration,
                                                            "limit": self.max_iterations},
                                                           separators=(",", ":")))
                    log.info(unique_id=unique_id, event="Анализ завершён моделью",
                             description=self._answer_log_metadata(answer))
                    return await self._finalize(session, unique_id)

                if choice.finish_reason != FinishReasonType.tool_calls:
                    self._raise_terminal_error(answer, unique_id, "analysis")

                if not choice.message.tool_calls:
                    log.warning(unique_id=unique_id, event="Получен пустой список вызовов инструментов",
                                description=self._answer_log_metadata(answer))
                    return await self._finalize(session, unique_id)

                log.info(unique_id=unique_id, event="Получены вызовы инструментов",
                         description=self._answer_log_metadata(answer))

                tool_messages = await self._execute_calls(
                    unique_id, choice.message.tool_calls or [], analysis_context
                )
                if (task.count_tool_calls >= self.max_tool_calls
                        or task.current_iteration >= self.max_iterations):
                    if task.count_tool_calls >= self.max_tool_calls:
                        log.warning(unique_id=unique_id, event="Достигнут лимит вызовов инструментов",
                                    description=json.dumps({"used": task.count_tool_calls,
                                                            "limit": self.max_tool_calls},
                                                           separators=(",", ":")))
                    if task.current_iteration >= self.max_iterations:
                        log.warning(unique_id=unique_id, event="Достигнут лимит итераций",
                                    description=json.dumps({"used": task.current_iteration,
                                                            "limit": self.max_iterations},
                                                           separators=(",", ":")))
                    return await self._finalize(session, unique_id, tool_messages)

                answer = await self._retry_provider(
                    session, await session.send(messages=tool_messages), unique_id, "analysis"
                )
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
        log.info(unique_id=data.unique_id, event="Запрос принят",
                 description=json.dumps({"status": "accepted"}, separators=(",", ":")))
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
            result = await self.run_loop(data.unique_id, graph, metrics, context)
            log.info(unique_id=data.unique_id, event="Задача успешно завершена",
                     description=json.dumps({"iterations": task.current_iteration,
                                             "tool_calls": task.count_tool_calls},
                                            separators=(",", ":")))
            return result
        except asyncio.CancelledError:
            log.warning(unique_id=data.unique_id, event="Задача отменена",
                        description=json.dumps({"exception_type": "CancelledError",
                                                "iterations": task.current_iteration,
                                                "tool_calls": task.count_tool_calls},
                                               separators=(",", ":")))
            raise
        except Exception as exc:
            log.error(unique_id=data.unique_id, event="Задача завершена с ошибкой",
                      description=json.dumps({"exception_type": type(exc).__name__,
                                              "iterations": task.current_iteration,
                                              "tool_calls": task.count_tool_calls},
                                             separators=(",", ":")))
            raise
        finally:
            task.status = TaskStatus.done
            await log.flush_async()

    async def _finalize(self, session, unique_id: int, prior_messages: list | None = None) -> str:
        log.info(unique_id=unique_id, event="Запрошен финальный ответ",
                 description=json.dumps({"phase": "finalize"}, separators=(",", ":")))
        prompt = self.message_validator.create_message(
            "Анализ завершён. Сформируй итоговый отчёт в соответствии с JSON-контрактом. "
            "Используй только полученные данные. Не вызывай инструменты. Верни исключительно JSON."
        )
        answer = await self._retry_provider(
            session, await session.final_send(messages=[*(prior_messages or []), prompt]),
            unique_id, "finalize",
        )
        choice = answer.choices[0]
        if choice.finish_reason != FinishReasonType.stop:
            log.error(unique_id=unique_id, event="Финальный ответ завершён нештатно",
                       description=self._answer_log_metadata(answer, phase="finalize"))
            raise FinalAnswerAbsent("Не удалось получить финальный JSON", answer.model_dump())
        content = choice.message.content
        if not content or not content.strip():
            log.error(unique_id=unique_id, event="Получен пустой финальный ответ",
                       description=self._answer_log_metadata(answer, phase="finalize"))
            raise FinalAnswerAbsent("LLM вернула пустой JSON-ответ", answer.model_dump())
        try:
            analysis = LLMAnalysis.model_validate_json(content)
        except Exception as exc:
            log.error(unique_id=unique_id, event="Ошибка валидации финального ответа",
                       description=self._answer_log_metadata(
                           answer, phase="finalize", exception_type=type(exc).__name__,
                       ))
            raise
        result = analysis.model_dump_json()
        log.info(unique_id=unique_id, event="Финальный ответ принят",
                  description=self._answer_log_metadata(
                      answer, phase="finalize",
                      serialized_utf8_size=len(result.encode("utf-8")),
                      issues_count=len(analysis.issues),
                      strengths_count=len(analysis.strengths),
                  ))
        return result
