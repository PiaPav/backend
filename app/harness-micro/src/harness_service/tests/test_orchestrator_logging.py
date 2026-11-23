import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import core_server.logic.orchestrator as orchestrator_module
from core_server.logic.orchestrator import (
    ContentFilterTriggered, GenerationAborted, GenerationLengthExceeded, HarnessError,
    Orchestrator, ProviderUnavailable,
)
from core_server.models.task_models import HarnessInputData
from response_models.models import FinishReasonType, FunctionCall, Prompt, Role, ToolCall, ToolResponse
from tools_engine.interface.tool import ToolError
from tools_engine.models.tool_result import ToolResult
from utils.logger.db.logs_orm import _extract_llm_usage


FINAL_JSON = '{"issues":[],"strengths":[]}'


def answer(reason, *, calls=None, content=None):
    return SimpleNamespace(
        choices=[SimpleNamespace(
            finish_reason=FinishReasonType(reason),
            message=SimpleNamespace(tool_calls=calls, content=content),
        )],
        model_dump=lambda: {},
    )


class RecordingLog:
    def __init__(self):
        self.records = []
        self.flushes = 0

    def _record(self, level, **kwargs):
        self.records.append((level, kwargs["event"], json.loads(kwargs["description"])))

    def info(self, **kwargs): self._record("INFO", **kwargs)
    def warning(self, **kwargs): self._record("WARNING", **kwargs)
    def error(self, **kwargs): self._record("ERROR", **kwargs)

    async def flush_async(self):
        self.flushes += 1


class Validator:
    def create_start_messages(self, *args):
        return [Prompt(role=Role.system, content="safe overview")]

    def load_tools_models(self): return []
    def create_message(self, content): return Prompt(role=Role.system, content=content)
    def create_tool_message(self, call, content):
        return ToolResponse(tool_call_id=call.id, content=content)


class Session:
    def __init__(self, start, *, sends=(), final=None, retries=()):
        self.start = start
        self.sends = list(sends)
        self.final = final or answer("stop", content=FINAL_JSON)
        self.retries = list(retries)
        self.sent = []
        self.final_count = 0

    async def send_start(self, **kwargs): return self.start
    async def send(self, messages):
        self.sent.append(messages)
        return self.sends.pop(0)
    async def final_send(self, messages):
        self.final_count += 1
        return self.final
    async def retry_send(self): return self.retries.pop(0)


class Connector:
    def __init__(self, session): self.session, self.closed = session, 0
    async def create_session(self, unique_id): return self.session
    async def close_session(self, unique_id): self.closed += 1


class Engine:
    def __init__(self, result=None): self.result = result or ToolResult.success({"safe": True})
    def start(self): pass
    async def entry_tool(self, **kwargs): return self.result


def call(arguments="{}"):
    return ToolCall(id="call-1", function=FunctionCall(name="GET-CONTENT", arguments=arguments))


def make(session, *, engine=None, calls=2, iterations=3, retries=2):
    return Orchestrator(
        Connector(session), engine or Engine(), Validator(), max_tool_calls=calls,
        max_iterations=iterations, max_start_context_size=10_000,
        max_provider_retries=retries,
    )


def data(tmp_path: Path):
    graph, metrics = tmp_path / "graph.json", tmp_path / "metrics.json"
    graph.write_text("graph", encoding="utf-8")
    metrics.write_text("metrics", encoding="utf-8")
    return HarnessInputData(
        7, {"aggregate.overview": graph}, {"metrics.overview": metrics},
        tmp_path / "index.json", "g" * 64, "p" * 64,
    )


@pytest.fixture
def records(monkeypatch):
    logger = RecordingLog()
    monkeypatch.setattr(orchestrator_module, "log", logger)
    return logger


def events(records): return [record[1] for record in records.records]


def test_happy_path_logs_branches_tool_final_and_lifecycle(tmp_path, records):
    final = answer("stop", content=FINAL_JSON)
    final.id = "final-response-123"
    final.model = "final-model"
    final.usage = SimpleNamespace(
        prompt_tokens=21, completion_tokens=9, total_tokens=30,
        prompt_cache_hit_tokens=4, prompt_cache_miss_tokens=17,
    )
    session = Session(
        answer("tool_calls", calls=[call()]), sends=[answer("stop")], final=final,
    )
    service = make(session)

    assert asyncio.run(service.run_task(data(tmp_path))) == FINAL_JSON

    assert "Получены вызовы инструментов" in events(records)
    assert "Анализ завершён моделью" in events(records)
    assert "Запрошен финальный ответ" in events(records)
    assert "Финальный ответ принят" in events(records)
    assert "Задача успешно завершена" in events(records)
    assert events(records).count("Обработан вызов инструмента") == 1
    assert records.flushes == 1
    assert service.llm_connector.closed == 1
    assert "Получен ответ LLM" not in events(records)
    branch_events = {
        "Получены вызовы инструментов", "Анализ завершён моделью",
        "Финальный ответ принят",
    }
    assert [event for event in events(records) if event in branch_events] == [
        "Получены вызовы инструментов", "Анализ завершён моделью",
        "Финальный ответ принят",
    ]
    final_log = next(item for item in records.records if item[1] == "Финальный ответ принят")
    assert _extract_llm_usage(json.dumps(final_log[2])) == {
        "llm_model": "final-model", "llm_response_id": "final-response-123",
        "finish_reason": "stop", "prompt_tokens": 21,
        "completion_tokens": 9, "total_tokens": 30,
        "prompt_cache_hit_tokens": 4, "prompt_cache_miss_tokens": 17,
    }
    expected_result_metadata = {
        "phase": "finalize", "serialized_utf8_size": len(FINAL_JSON.encode("utf-8")),
        "issues_count": 0, "strengths_count": 0,
    }
    assert {key: final_log[2][key] for key in expected_result_metadata} == expected_result_metadata


def test_premature_stop_logs_branch_and_sends_correction(tmp_path, records):
    session = Session(answer("stop"), sends=[answer("tool_calls", calls=[])])
    asyncio.run(make(session).run_task(data(tmp_path)))
    assert events(records).count("Преждевременная остановка анализа") == 1
    assert "подтверди гипотезы" in session.sent[0][0].content


def test_repeated_premature_stop_logs_iteration_limit_before_finalizing(tmp_path, records):
    session = Session(answer("stop"), sends=[answer("stop")])

    asyncio.run(make(session, iterations=2).run_task(data(tmp_path)))

    assert events(records).count("Преждевременная остановка анализа") == 1
    assert events(records).count("Достигнут лимит итераций") == 1
    limit_log = next(item for item in records.records if item[1] == "Достигнут лимит итераций")
    assert limit_log == ("WARNING", "Достигнут лимит итераций", {"used": 2, "limit": 2})
    assert events(records).count("Анализ завершён моделью") == 1
    assert "Получен ответ LLM" not in events(records)
    assert session.final_count == 1


@pytest.mark.parametrize("reason,error,event,level", [
    ("length", GenerationLengthExceeded, "Превышен лимит генерации", "ERROR"),
    ("content_filter", ContentFilterTriggered, "Сработал фильтр содержимого", "ERROR"),
    ("aborted", GenerationAborted, "Генерация прервана", "WARNING"),
    ("unknown_reason", HarnessError, "Неизвестная причина завершения генерации", "ERROR"),
])
def test_terminal_reasons_are_logged_safely(tmp_path, records, reason, error, event, level):
    marker = "SECRET-TERMINAL-PAYLOAD"
    response = answer("stop", content=marker) if reason == "unknown_reason" else answer(reason, content=marker)
    if reason == "unknown_reason":
        response.choices[0].finish_reason = reason
    response.id = "terminal-response-123"
    response.model = "terminal-model"
    response.usage = SimpleNamespace(prompt_tokens=8, completion_tokens=3, total_tokens=11)
    with pytest.raises(error):
        asyncio.run(make(Session(response)).run_task(data(tmp_path)))
    terminal_log = next(item for item in records.records if item[1] == event)
    assert terminal_log[:2] == (level, event)
    assert terminal_log[2]["phase"] == "analysis"
    assert _extract_llm_usage(json.dumps(terminal_log[2])) == {
        "llm_model": "terminal-model", "llm_response_id": "terminal-response-123",
        "finish_reason": reason, "prompt_tokens": 8,
        "completion_tokens": 3, "total_tokens": 11,
        "prompt_cache_hit_tokens": None, "prompt_cache_miss_tokens": None,
    }
    assert marker not in json.dumps(terminal_log[2])


def test_provider_retry_recovery_and_exhaustion_include_phase_and_attempt(tmp_path, records, monkeypatch):
    async def no_sleep(_): pass
    monkeypatch.setattr(orchestrator_module.asyncio, "sleep", no_sleep)
    marker = "SECRET-PROVIDER-PAYLOAD"
    retry_response = answer("insufficient_system_resource", content=marker)
    retry_response.id = "retry-response-123"
    retry_response.model = "retry-model"
    retry_response.usage = {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6}
    recovered = Session(retry_response,
                        retries=[answer("tool_calls", calls=[])])
    asyncio.run(make(recovered).run_task(data(tmp_path)))
    retry = next(item for item in records.records if item[1] == "Повтор запроса к провайдеру")
    assert retry[2]["phase"] == "analysis"
    assert retry[2]["attempt"] == 1
    assert _extract_llm_usage(json.dumps(retry[2])) == {
        "llm_model": "retry-model", "llm_response_id": "retry-response-123",
        "finish_reason": "insufficient_system_resource", "prompt_tokens": 5,
        "completion_tokens": 1, "total_tokens": 6,
        "prompt_cache_hit_tokens": None, "prompt_cache_miss_tokens": None,
    }
    assert marker not in json.dumps(retry[2])

    exhausted_response = answer("insufficient_system_resource", content=marker)
    exhausted_response.id = "exhausted-response-456"
    exhausted_response.model = "exhausted-model"
    exhausted_response.usage = SimpleNamespace(
        prompt_tokens=9, completion_tokens=2, total_tokens=11)
    exhausted = Session(answer("insufficient_system_resource"), retries=[
        answer("insufficient_system_resource"), exhausted_response])
    with pytest.raises(ProviderUnavailable):
        asyncio.run(make(exhausted).run_task(data(tmp_path)))
    exhausted_log = [item for item in records.records
                     if item[1] == "Исчерпаны повторы запроса к провайдеру"][-1]
    assert exhausted_log[2]["phase"] == "analysis"
    assert exhausted_log[2]["attempts"] == 2
    assert _extract_llm_usage(json.dumps(exhausted_log[2])) == {
        "llm_model": "exhausted-model", "llm_response_id": "exhausted-response-456",
        "finish_reason": "insufficient_system_resource", "prompt_tokens": 9,
        "completion_tokens": 2, "total_tokens": 11,
        "prompt_cache_hit_tokens": None, "prompt_cache_miss_tokens": None,
    }
    assert marker not in json.dumps(exhausted_log[2])


def test_provider_retry_during_finalize_has_finalize_phase(tmp_path, records, monkeypatch):
    async def no_sleep(_): pass
    monkeypatch.setattr(orchestrator_module.asyncio, "sleep", no_sleep)
    session = Session(
        answer("tool_calls", calls=[]),
        final=answer("insufficient_system_resource"),
        retries=[answer("stop", content=FINAL_JSON)],
    )

    assert asyncio.run(make(session).run_task(data(tmp_path))) == FINAL_JSON
    retry = next(item for item in records.records if item[1] == "Повтор запроса к провайдеру")
    assert retry[:2] == ("WARNING", "Повтор запроса к провайдеру")
    assert retry[2]["phase"] == "finalize"
    assert retry[2]["attempt"] == 1
    assert events(records).count("Финальный ответ принят") == 1


@pytest.mark.parametrize("calls_limit,iterations,event", [
    (1, 3, "Достигнут лимит вызовов инструментов"),
    (4, 1, "Достигнут лимит итераций"),
])
def test_empty_calls_and_limits_have_distinct_events_and_one_finalize(
    tmp_path, records, calls_limit, iterations, event,
):
    empty = Session(answer("tool_calls", calls=[]))
    asyncio.run(make(empty).run_task(data(tmp_path)))
    assert "Получен пустой список вызовов инструментов" in events(records)
    assert empty.final_count == 1

    limited = Session(answer("tool_calls", calls=[call()]))
    asyncio.run(make(limited, calls=calls_limit, iterations=iterations).run_task(data(tmp_path)))
    assert event in events(records)
    assert limited.final_count == 1


@pytest.mark.parametrize("final,event", [
    (answer("tool_calls", calls=[]), "Финальный ответ завершён нештатно"),
    (answer("stop", content=" "), "Получен пустой финальный ответ"),
    (answer("stop", content="SECRET-PAYLOAD"), "Ошибка валидации финального ответа"),
])
def test_final_answer_failures_have_distinct_events(tmp_path, records, final, event):
    final.id = "failed-final-response-123"
    final.model = "failed-final-model"
    final.usage = SimpleNamespace(
        prompt_tokens=13, completion_tokens=5, total_tokens=18,
        prompt_cache_hit_tokens=2, prompt_cache_miss_tokens=11,
    )
    session = Session(answer("tool_calls", calls=[]), final=final)
    with pytest.raises(Exception):
        asyncio.run(make(session).run_task(data(tmp_path)))
    assert event in events(records)
    failure_log = next(item for item in records.records if item[1] == event)
    assert failure_log[2]["phase"] == "finalize"
    assert _extract_llm_usage(json.dumps(failure_log[2])) == {
        "llm_model": "failed-final-model", "llm_response_id": "failed-final-response-123",
        "finish_reason": final.choices[0].finish_reason.value, "prompt_tokens": 13,
        "completion_tokens": 5, "total_tokens": 18,
        "prompt_cache_hit_tokens": 2, "prompt_cache_miss_tokens": 11,
    }
    assert "SECRET-PAYLOAD" not in json.dumps(failure_log[2])


def test_tool_error_is_warning_and_metadata_does_not_leak_secrets(tmp_path, records):
    marker = "SECRET-MARKER"
    failure = ToolResult.failure(ToolError(
        marker, {"details": marker}, True, code="safe_code",
    ))
    session = Session(answer("tool_calls", calls=[call(marker)]), sends=[answer("stop")])
    asyncio.run(make(session, engine=Engine(failure)).run_task(data(tmp_path)))
    tool_log = next(item for item in records.records if item[1] == "Обработан вызов инструмента")
    assert tool_log[0] == "WARNING"
    assert tool_log[2]["diagnostics"] == [{"code": "safe_code", "retryable": True}]
    assert marker not in json.dumps(tool_log[2])


@pytest.mark.parametrize("cancelled", [False, True])
def test_task_error_and_cancellation_are_safe_and_flushed(tmp_path, records, cancelled):
    marker = "SECRET-EXCEPTION-TEXT"

    class FailingSession(Session):
        async def send_start(self, **kwargs):
            if cancelled:
                raise asyncio.CancelledError(marker)
            raise RuntimeError(marker)

    service = make(FailingSession(answer("stop")))
    expected = asyncio.CancelledError if cancelled else RuntimeError
    with pytest.raises(expected):
        asyncio.run(service.run_task(data(tmp_path)))

    task_event = "Задача отменена" if cancelled else "Задача завершена с ошибкой"
    task_log = next(item for item in records.records if item[1] == task_event)
    assert task_log[0] == ("WARNING" if cancelled else "ERROR")
    assert marker not in json.dumps(task_log[2])
    assert records.flushes == 1
    assert service.llm_connector.closed == 1


def test_answer_metadata_preserves_safe_db_analytics_without_payloads():
    marker = "SECRET-PAYLOAD"
    response = answer("tool_calls", calls=[call(marker)], content=marker)
    response.id = "response-123"
    response.model = "safe-model"
    response.usage = SimpleNamespace(
        prompt_tokens=11, completion_tokens=7, total_tokens=18,
        prompt_cache_hit_tokens=3, prompt_cache_miss_tokens=8,
    )

    metadata = Orchestrator._answer_log_metadata(response)
    extracted = _extract_llm_usage(metadata)

    assert extracted == {
        "llm_model": "safe-model", "llm_response_id": "response-123",
        "finish_reason": "tool_calls", "prompt_tokens": 11,
        "completion_tokens": 7, "total_tokens": 18,
        "prompt_cache_hit_tokens": 3, "prompt_cache_miss_tokens": 8,
    }
    assert marker not in metadata
