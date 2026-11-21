import time
import json
from pathlib import Path
import asyncio

from core_server.interfaces.orchestrator import OrchestratorInterface
from core_server.models.task_models import TaskInfo, TaskStatus, HarnessInputData
from llm_connector.interfaces.connector import LLMConnectorInterface
from llm_connector.interfaces.validator import ValidatorInterface
from response_models.models import FinishReasonType, ToolCall, LLMAnalysis
from tools_engine.interface.engine import EngineInterface
from tools_engine.interface.tool import ToolError
from tools_engine.models.analysis_context import AnalysisContext
from tools_engine.models.tool_result import ToolResult
from utils.logger import create_logger

TASK_EXPIRED_TIME_MIN = 60 * 60 # 60 минут, в секунды
MAX_COUNT_TOOL_CALLS = 3
COUNT_MESSAGES = MAX_COUNT_TOOL_CALLS + 1


class HarnessError(Exception):

    def __init__(self, message: str, details: dict = None, *args, **kwargs):
        self.error = {"message": message, "details": details}
        super().__init__(message)

    @property
    def name(self) -> str:
        return self.__class__.__name__

    def __str__(self):
        return f"{self.name}: {self.error}"


class GenerationLengthExceeded(HarnessError):
    """Ошибка со стороны модели. Генерация завершена из-за превышения лимита токенов / контекстного окна."""
    pass

class ContentFilterTriggered(HarnessError):
    """Ошибка со стороны модели. Сработал фильтр текста."""
    pass

class ProviderUnavailable(HarnessError):
    """Ошибка со стороны модели. Провайдер перегружен и не может обслужить запросы"""
    pass

class GenerationAborted(HarnessError):
    """Ошибка со стороны модели. Генерация оборвалась."""
    pass

class FinalAnswerAbsent(HarnessError):
    """Ошибка со стороны модели. Отсутствует финальный ответ."""
    pass


log = create_logger("Orchestrator")


class Orchestrator(OrchestratorInterface):

    def __init__(self, llm_connector: LLMConnectorInterface, tools_engine: EngineInterface,
                 validator: ValidatorInterface):
        self.tasks: dict[int, TaskInfo] = {}
        self.llm_connector: LLMConnectorInterface = llm_connector
        self.tools_engine: EngineInterface = tools_engine
        self.message_validator: ValidatorInterface = validator

    async def start(self, url, apikey):
        """Запустить систему"""
        await self.llm_connector.connect(url, apikey)
        self.tools_engine.start()

    def _clear_old_tasks(self):
        """Удалить устаревшие задачи"""
        current_time = self._now()
        for task_id in self.tasks:
            if (self.tasks[task_id].expire_time < current_time and
                    self.tasks[task_id].status == TaskStatus.done):
                self.tasks.pop(task_id)
            else:
                break

    def _load_file(self, path: Path) -> str:
        """Загрузчик файлов (в будущем мб перекатить на редис)"""
        return path.read_text(encoding="utf-8")

    @staticmethod
    def _now() -> float:
        """Текущее время"""
        return time.perf_counter()

    @staticmethod
    def _tool_log_metadata(tool_name: str, result: ToolResult) -> str:
        metadata = {
            "tool_name": tool_name,
            "status": result.status,
            "profile_id": result.profile_id,
            "completeness": {
                "returned": result.completeness.returned,
                "total": result.completeness.total,
                "truncated": result.completeness.truncated,
            },
            "serialized_utf8_size": result.utf8_size(),
        }
        return json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _answer_log_metadata(answer) -> str:
        choice = answer.choices[0]
        tool_calls = getattr(choice.message, "tool_calls", None) or []
        finish_reason = choice.finish_reason
        metadata = {
            "finish_reason": getattr(finish_reason, "value", finish_reason),
            "tool_call_count": len(tool_calls),
            "tool_names": [tool_call.function.name for tool_call in tool_calls],
        }
        return json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))

    async def run_loop(self, unique_id: int, graph: str, metrix: str,
                       analysis_context: AnalysisContext) -> str:
        """Цикл общения с нейронкой"""
        log.info(unique_id=unique_id, event="Принят запрос", description="")

        session = await self.llm_connector.create_session(unique_id)

        messages = self.message_validator.create_start_messages(graph, metrix)
        tools = self.message_validator.load_tools_models()

        # отправка первого сообщения
        answer = await session.send_start(messages=messages, tools=tools)
        log.info(unique_id=unique_id, event=f"Отправлено сообщение {self.tasks[unique_id].current_iteration}",
                 description="")
        self.tasks[unique_id].current_iteration += 1

        # Цикл запрос-ответ
        while self.tasks[unique_id].current_iteration <= COUNT_MESSAGES and self.tasks[unique_id].count_tool_calls <= MAX_COUNT_TOOL_CALLS:
            choice = answer.choices[0]
            # Получен ответ
            if choice.finish_reason == FinishReasonType.stop:
                # Преждевременное завершение
                if self.tasks[unique_id].count_tool_calls == 0:
                    log.warning(unique_id=unique_id, event=f"Попытка преждевременного завершения {self.tasks[unique_id].current_iteration}", description=self._answer_log_metadata(answer))
                    # print(f"ЛЛМ пытается закончить анализ, не вызвав инструменты")
                    # Нужно отправить промт с указанием использовать тулы перед финальным ответом
                    message = self.message_validator.create_message("Перед формированием финального ответа необходимо подтвердить имеющиеся гипотезы с помощью вызова инструментов. "
                                                                    "Поэтому в следующем ответе воспользуйся имеющимся инструментарием.")
                    answer = await session.send(messages=[message])

                else:
                    log.info(unique_id=unique_id, event=f"Модель закончила рассуждения {self.tasks[unique_id].current_iteration}", description=self._answer_log_metadata(answer))
                    # print(f"Итерации закончились, получен итоговый ответ")
                    return await self._finalize(session=session, unique_id=unique_id)

            # Получен вызов тулы
            elif choice.finish_reason == FinishReasonType.tool_calls:
                log.info(unique_id=unique_id, event=f"Получен ответ с вызовом {self.tasks[unique_id].current_iteration}", description=self._answer_log_metadata(answer))
                tool_calls: list[ToolCall] = choice.message.tool_calls

                tool_messages = []

                # Перебираем все вызовы тулов
                for tool_call in tool_calls:
                    # Перебор по тулам
                    if self.tasks[unique_id].count_tool_calls >= MAX_COUNT_TOOL_CALLS:
                        # Нужно остановить и вернуть нейронке, что она исчерпала лимит
                        result = ToolResult.failure(ToolError(
                            f"Исчерпан лимит использования инструментов. Использовано {self.tasks[unique_id].count_tool_calls} из {MAX_COUNT_TOOL_CALLS}.",
                            {"limit": MAX_COUNT_TOOL_CALLS}, False,
                            code="tool_call_limit_exceeded",
                        ))
                        message = self.message_validator.create_tool_message(tool_call, result.to_json())
                        log.warning(unique_id=unique_id, event=f"Превышен лимит вызовов инструментов {self.tasks[unique_id].current_iteration}", description=self._tool_log_metadata(tool_call.function.name, result))
                    # Все ок - исполняем
                    else:
                        function = tool_call.function
                        self.tasks[unique_id].count_tool_calls += 1
                        result = await self.tools_engine.entry_tool(
                            analysis_context=analysis_context,
                            name=function.name,
                            arguments=function.arguments
                        )
                        message = self.message_validator.create_tool_message(
                            tool_call, result.to_json()
                        )
                        log.info(unique_id=unique_id, event=f"Вызван инструмент {self.tasks[unique_id].current_iteration}", description=self._tool_log_metadata(function.name, result))

                    tool_messages.append(message)

                if self.tasks[unique_id].count_tool_calls >= MAX_COUNT_TOOL_CALLS:
                    # Исследовательский лимит достигнут. Передаём результаты и запрашиваем JSON.
                    final_prompt = (
                        "Лимит для анализа исчерпан. Дополнительные вызовы недоступны. Сформируй итоговый JSON"
                        "ответ исключительно на основе уже полученных результатов. Не придумывай результаты "
                        "отсутствующих проверок.")
                    final_message = self.message_validator.create_message(final_prompt)

                    log.info(unique_id=unique_id,
                             event=f"Лимит исчерпан. Отправлен запрос на получение финального ответа {self.tasks[unique_id].current_iteration}",
                             description="")
                    answer = await session.final_send(messages=[*tool_messages, final_message])

                    choice = answer.choices[0]

                    if choice.finish_reason != FinishReasonType.stop:
                        log.critical(unique_id=unique_id,
                                     event=f"Не удалось получить финальный JSON {self.tasks[unique_id].current_iteration}",
                                     description=self._answer_log_metadata(answer))
                        raise FinalAnswerAbsent("Не удалось получить финальный JSON", answer.model_dump())

                    content = choice.message.content

                    if not content or not content.strip():
                        log.critical(unique_id=unique_id,
                                     event=f"LLM вернула пустой JSON-ответ {self.tasks[unique_id].current_iteration}",
                                     description=self._answer_log_metadata(answer))
                        raise FinalAnswerAbsent("LLM вернула пустой JSON-ответ", answer.model_dump())

                    log.info(unique_id=unique_id,
                             event=f"Получен финальный ответ {self.tasks[unique_id].current_iteration}",
                             description=self._answer_log_metadata(answer))
                    return LLMAnalysis.model_validate_json(content).model_dump_json()

                answer = await session.send(messages=tool_messages)
                log.info(unique_id=unique_id, event=f"Отправлено сообщение с результатами инструментов {self.tasks[unique_id].current_iteration}",  description="")
                # print(f"Отправлено сообщение {self.tasks[unique_id].current_iteration}, получен ответ {self.tasks[unique_id].current_iteration}")

            elif choice.finish_reason == FinishReasonType.length:
                # Модель выдала обрезанный ответ, скорее всего из-за лимита токенов / контекстного окна
                log.error(unique_id=unique_id, event=f"Превышен лимит токенов / контекстного окна {self.tasks[unique_id].current_iteration}", description=self._answer_log_metadata(answer))
                # Выкатываем ошибку, надо передать ее до пользователя
                raise GenerationLengthExceeded("Генерация ответа остановлена из-за лимита токенов / контекстного окна", answer.model_dump())

            elif choice.finish_reason == FinishReasonType.content_filter:
                # Сработал фильтр. Партия Китай не знать ничего о происшествиях на площади Тяньаньмэнь!
                log.error(unique_id=unique_id, event=f"Сработал фильтр {self.tasks[unique_id].current_iteration}", description=self._answer_log_metadata(answer))
                raise ContentFilterTriggered("Сработал фильтр, продолжать обработку запроса невозможно", answer.model_dump())

            elif choice.finish_reason == FinishReasonType.insufficient_system_resource:
                # Перегрузка провайдера
                log.warning(unique_id=unique_id, event=f"Провайдер перегружен {self.tasks[unique_id].current_iteration}", description=self._answer_log_metadata(answer))
                delay = 2

                while delay <= 2**5:
                    await asyncio.sleep(delay)
                    answer = await session.retry_send()
                    if answer.choices[0].finish_reason != FinishReasonType.insufficient_system_resource:
                        break
                    delay *= 2

                else:
                    raise ProviderUnavailable("Провайдер перегружен, попробуй перезапустить позже", answer.model_dump())

            elif choice.finish_reason == FinishReasonType.aborted:
                # Генерация прервана
                log.warning(unique_id=unique_id, event=f"Генерация прервана {self.tasks[unique_id].current_iteration}", description=self._answer_log_metadata(answer))
                raise GenerationAborted("Генерация прервана, попробуй перезапустить позже", answer.model_dump())

            self.tasks[unique_id].current_iteration += 1

        # Делаем видоизмененную обработку крайних случаев
        final_answer = None

        choice = answer.choices[0]
        log.warning(unique_id=unique_id, event=f"Попытка продолжения сессии со стороны ЛЛМ, превышающая лимиты {self.tasks[unique_id].current_iteration}", description=self._answer_log_metadata(answer))
        # Получен ответ
        if choice.finish_reason == FinishReasonType.stop:
            log.info(unique_id=unique_id, event=f"Модель закончила рассуждения {self.tasks[unique_id].current_iteration}", description=self._answer_log_metadata(answer))
            return await self._finalize(session, unique_id)

        # Получен вызов тулы
        elif choice.finish_reason == FinishReasonType.tool_calls:
            log.warning(unique_id=unique_id, event=f"Получен ответ с вызовом {self.tasks[unique_id].current_iteration}", description=self._answer_log_metadata(answer))

            tool_calls: list[ToolCall] = choice.message.tool_calls

            messages = []

            # Перебираем все вызовы тулов
            for tool_call in tool_calls:
                # Перебор по тулам
                # Нужно остановить и вернуть нейронке, что она исчерпала лимит
                result = ToolResult.failure(ToolError(
                    f"Лимит для анализа исчерпан. Использовано сообщений: {self.tasks[unique_id].current_iteration} из {COUNT_MESSAGES}. Использовано инструментов: {self.tasks[unique_id].count_tool_calls} из {MAX_COUNT_TOOL_CALLS}",
                    {"message_limit": COUNT_MESSAGES, "tool_limit": MAX_COUNT_TOOL_CALLS},
                    False, code="tool_call_limit_exceeded",
                ))
                message = self.message_validator.create_tool_message(tool_call, result.to_json())
                log.warning(unique_id=unique_id,
                            event=f"Превышен лимит сообщений/инструментов {self.tasks[unique_id].current_iteration}",
                            description=self._tool_log_metadata(tool_call.function.name, result))

                messages.append(message)

            final_prompt = ("Лимит для анализа исчерпан. Дополнительные вызовы недоступны. Сформируй итоговый JSON"
                            "ответ исключительно на основе уже полученных результатов. Не придумывай результаты "
                            "отсутствующих проверок.")

            final_message = self.message_validator.create_message(msg=final_prompt)
            messages.append(final_message)

            final_answer = await session.final_send(messages=messages)


        elif choice.finish_reason == FinishReasonType.length:
            # Модель выдала обрезанный ответ, скорее всего из-за лимита токенов / контекстного окна
            log.error(unique_id=unique_id,
                      event=f"Превышен лимит токенов / контекстного окна {self.tasks[unique_id].current_iteration}",
                      description=self._answer_log_metadata(answer))
            # Выкатываем ошибку, надо передать ее до пользователя
            raise GenerationLengthExceeded("Генерация ответа остановлена из-за лимита токенов / контекстного окна",
                                           answer.model_dump())

        elif choice.finish_reason == FinishReasonType.content_filter:
            # Сработал фильтр. Партия Китай не знать ничего о происшествиях на площади Тяньаньмэнь!
            log.error(unique_id=unique_id, event=f"Сработал фильтр {self.tasks[unique_id].current_iteration}",
                      description=self._answer_log_metadata(answer))
            raise ContentFilterTriggered("Сработал фильтр, продолжать обработку запроса невозможно",
                                         answer.model_dump())

        elif choice.finish_reason == FinishReasonType.insufficient_system_resource:
            # Перегрузка провайдера
            log.warning(unique_id=unique_id, event=f"Провайдер перегружен {self.tasks[unique_id].current_iteration}",
                        description=self._answer_log_metadata(answer))
            delay = 2

            while delay <= 2 ** 5:
                await asyncio.sleep(delay)
                final_answer = await session.retry_send()
                if final_answer.choices[0].finish_reason != FinishReasonType.insufficient_system_resource:
                    break
                delay *= 2

            else:
                raise ProviderUnavailable("Провайдер перегружен, попробуй перезапустить позже", final_answer.model_dump())

        elif choice.finish_reason == FinishReasonType.aborted:
            # Генерация прервана
            log.warning(unique_id=unique_id, event=f"Генерация прервана {self.tasks[unique_id].current_iteration}",
                        description=self._answer_log_metadata(answer))
            raise GenerationAborted("Генерация прервана, попробуй перезапустить позже", answer.model_dump())

        # После обработки ждем ответ или после ошибочного tool_call или insufficient_system_resource
        if final_answer is None:
            log.critical(unique_id=unique_id,
                         event=f"Неизвестная причина завершения генерации {self.tasks[unique_id].current_iteration}",
                         description="")
            raise HarnessError("Неизвестная причина завершения генерации", answer.model_dump())

        if final_answer.choices[0].finish_reason == FinishReasonType.stop:
            content = final_answer.choices[0].message.content

            if not content or not content.strip():
                log.critical(unique_id=unique_id,
                             event=f"LLM вернула пустой JSON-ответ {self.tasks[unique_id].current_iteration}",
                             description=self._answer_log_metadata(final_answer))
                raise FinalAnswerAbsent("LLM вернула пустой JSON-ответ", final_answer.model_dump())
            log.info(unique_id=unique_id, event=f"Получен финальный ответ {self.tasks[unique_id].current_iteration}",
                     description=self._answer_log_metadata(final_answer))

            return LLMAnalysis.model_validate_json(content).model_dump_json()

        # Ответа так и не последовало
        log.critical(unique_id=unique_id, event=f"Отсутствует финальный ответ {self.tasks[unique_id].current_iteration}", description=self._answer_log_metadata(final_answer))
        raise FinalAnswerAbsent("Отсутствует финальный ответ от ЛЛМ", final_answer.model_dump())

    async def run_task(self, data: HarnessInputData) -> str:
        """Передать задачу ллм"""
        try:
            self.tasks[data.unique_id] = TaskInfo(
                unique_id=data.unique_id,
                current_iteration=0,
                expire_time=self._now() + TASK_EXPIRED_TIME_MIN,
                status=TaskStatus.accept,
                count_tool_calls=0
            )

            analysis_context = AnalysisContext(
                task_id=data.unique_id,
                graph_profiles=data.graph_profiles,
                metrics_profiles=data.metrics_profiles,
                source_index_path=data.source_index_path,
                graph_fingerprint=data.graph_fingerprint,
                project_fingerprint=data.project_fingerprint,
            )
            graph = self._load_file(analysis_context.graph_profiles["canonical.full"])
            metrix = self._load_file(analysis_context.metrics_profiles["metrics.full"])

            result = await self.run_loop(data.unique_id, graph, metrix, analysis_context)

            return result

        finally:
            await log.flush_async()


    async def _finalize(self, session, unique_id) -> str:
        prompt = self.message_validator.create_message(
            "Анализ завершён. Сформируй итоговый отчёт "
            "в соответствии с JSON-контрактом. "
            "Используй только полученные данные. "
            "Не вызывай инструменты. "
            "Верни исключительно JSON."
        )

        log.info(unique_id=unique_id, event=f"Отправлен запрос на получение финального ответа {self.tasks[unique_id].current_iteration}", description="")
        answer = await session.final_send(messages=[prompt])

        choice = answer.choices[0]

        if choice.finish_reason != FinishReasonType.stop:
            log.critical(unique_id=unique_id, event=f"Не удалось получить финальный JSON {self.tasks[unique_id].current_iteration}",
                     description=self._answer_log_metadata(answer))
            raise FinalAnswerAbsent("Не удалось получить финальный JSON", answer.model_dump())

        content = choice.message.content

        if not content or not content.strip():
            log.critical(unique_id=unique_id, event=f"LLM вернула пустой JSON-ответ {self.tasks[unique_id].current_iteration}",
                     description=self._answer_log_metadata(answer))
            raise FinalAnswerAbsent("LLM вернула пустой JSON-ответ", answer.model_dump())

        log.info(unique_id=unique_id, event=f"Получен финальный ответ {self.tasks[unique_id].current_iteration}", description=self._answer_log_metadata(answer))

        return LLMAnalysis.model_validate_json(content).model_dump_json()

