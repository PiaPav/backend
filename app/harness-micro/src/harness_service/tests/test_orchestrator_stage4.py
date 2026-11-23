import asyncio
from pathlib import Path
from types import SimpleNamespace

from core_server.interfaces.errors import InvalidHarnessInput
from core_server.logic.orchestrator import Orchestrator, ProviderUnavailable
from core_server.models.task_models import HarnessInputData, TaskStatus
from response_models.models import FinishReasonType, FunctionCall, Prompt, Role, ToolCall, ToolResponse
from tools_engine.models.tool_result import ToolResult


FINAL_JSON = '{"issues":[],"strengths":[]}'


def answer(reason, *, calls=None, content=None):
    reason = FinishReasonType(reason)
    choice = SimpleNamespace(
        finish_reason=reason,
        message=SimpleNamespace(tool_calls=calls, content=content),
    )
    return SimpleNamespace(choices=[choice], model_dump=lambda: {})


class Validator:
    def __init__(self):
        self.start_args = None

    def create_start_messages(self, graph, metrics, graph_ids, metrics_ids, budget):
        self.start_args = graph, metrics, graph_ids, metrics_ids, budget
        return [Prompt(role=Role.system, content=f"{graph}\n{metrics}\n{graph_ids}\n{metrics_ids}\n{budget}")]

    def load_tools_models(self):
        return []

    def create_tool_message(self, call, content):
        return ToolResponse(tool_call_id=call.id, content=content)

    def create_message(self, msg):
        return Prompt(role=Role.system, content=msg)


class Session:
    def __init__(self, start_answer):
        self.start_answer = start_answer
        self.final_calls = []

    async def send_start(self, **kwargs):
        return self.start_answer

    async def send(self, messages):
        return answer("stop", content="ignored")

    async def final_send(self, messages):
        self.final_calls.append(messages)
        return answer("stop", content=FINAL_JSON)

    async def retry_send(self):
        raise AssertionError("retry was not expected")


class Connector:
    def __init__(self, session):
        self.session = session
        self.created = 0
        self.closed = 0

    async def create_session(self, unique_id):
        self.created += 1
        return self.session

    async def close_session(self, unique_id):
        self.closed += 1


class Engine:
    def __init__(self):
        self.calls = []

    async def entry_tool(self, **kwargs):
        self.calls.append(kwargs)
        return ToolResult.success({"ok": True})


def input_data(tmp_path: Path, *, graph_extra=None):
    graph = tmp_path / "overview-graph.json"
    metrics = tmp_path / "overview-metrics.json"
    graph.write_text("граф", encoding="utf-8")
    metrics.write_text("метрики", encoding="utf-8")
    graphs = {"aggregate.overview": graph, "z": graph, "a": graph}
    if graph_extra is not None:
        graphs = graph_extra
    return HarnessInputData(
        1, graphs, {"metrics.overview": metrics, "b": metrics},
        tmp_path / "index.json", "g" * 64, "p" * 64,
    )


def make_orchestrator(connector, engine, validator, *, size=10_000):
    return Orchestrator(
        connector, engine, validator, max_tool_calls=6,
        max_iterations=8, max_start_context_size=size, max_provider_retries=2,
    )


def test_overview_context_sorted_catalogs_partial_batch_and_single_finalize(tmp_path: Path):
    calls = [
        ToolCall(id=str(index), function=FunctionCall(name="GET-CONTENT", arguments="{}"))
        for index in range(7)
    ]
    session = Session(answer("tool_calls", calls=calls))
    connector = Connector(session)
    engine = Engine()
    validator = Validator()
    orchestrator = make_orchestrator(connector, engine, validator)

    result = asyncio.run(orchestrator.run_task(input_data(tmp_path)))

    assert result == FINAL_JSON
    assert validator.start_args == (
        "граф", "метрики", ["a", "aggregate.overview", "z"],
        ["b", "metrics.overview"], 6,
    )
    assert len(engine.calls) == 6
    assert len(session.final_calls) == 1
    assert len(session.final_calls[0]) == 8  # seven call IDs and final prompt
    assert "tool_call_limit_exceeded" in session.final_calls[0][6].content
    assert connector.closed == 1
    assert orchestrator.tasks[1].status is TaskStatus.done

    class BlockingSession(Session):
        async def send_start(self, **kwargs):
            await asyncio.sleep(60)

    async def cancel_task(orchestrator, data):
        task = asyncio.create_task(orchestrator.run_task(data))
        await asyncio.sleep(0)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    connector = Connector(BlockingSession(answer("stop")))
    orchestrator = make_orchestrator(connector, Engine(), Validator())
    asyncio.run(cancel_task(orchestrator, input_data(tmp_path)))
    assert connector.closed == 1
    assert orchestrator.tasks[1].status is TaskStatus.done


def test_missing_overview_and_size_limit_fail_before_session(tmp_path: Path):
    session = Session(answer("stop"))
    connector = Connector(session)
    orchestrator = make_orchestrator(connector, Engine(), Validator())
    data = input_data(tmp_path, graph_extra={"canonical.full": tmp_path / "unused"})

    try:
        asyncio.run(orchestrator.run_task(data))
    except InvalidHarnessInput:
        pass
    else:
        raise AssertionError("legacy input without overview must be rejected")
    assert connector.created == 0

    connector = Connector(session)
    orchestrator = make_orchestrator(connector, Engine(), Validator(), size=1)
    try:
        asyncio.run(orchestrator.run_task(input_data(tmp_path)))
    except InvalidHarnessInput:
        pass
    else:
        raise AssertionError("oversized UTF-8 context must be rejected")
    assert connector.created == 0


def test_session_closes_once_on_error_and_cancellation(tmp_path: Path):
    class FailingSession(Session):
        async def send_start(self, **kwargs):
            raise RuntimeError("provider failed")

    connector = Connector(FailingSession(answer("stop")))
    orchestrator = make_orchestrator(connector, Engine(), Validator())
    try:
        asyncio.run(orchestrator.run_task(input_data(tmp_path)))
    except RuntimeError:
        pass
    else:
        raise AssertionError("provider error must be propagated")
    assert connector.closed == 1
    assert orchestrator.tasks[1].status is TaskStatus.done


def test_empty_tool_calls_finalize_instead_of_looping(tmp_path: Path):
    session = Session(answer("tool_calls", calls=[]))
    result = asyncio.run(make_orchestrator(
        Connector(session), Engine(), Validator()
    ).run_task(input_data(tmp_path)))
    assert result == FINAL_JSON
    assert len(session.final_calls) == 1


def test_provider_retry_exhaustion_is_bounded_and_does_not_use_tool_budget(tmp_path: Path):
    class TransientSession(Session):
        def __init__(self):
            super().__init__(answer("insufficient_system_resource"))
            self.retries = 0

        async def retry_send(self):
            self.retries += 1
            return answer("insufficient_system_resource")

    session = TransientSession()
    orchestrator = make_orchestrator(Connector(session), Engine(), Validator())
    original_sleep = asyncio.sleep

    async def no_sleep(_delay):
        return None

    asyncio.sleep = no_sleep
    try:
        try:
            asyncio.run(orchestrator.run_task(input_data(tmp_path)))
        except ProviderUnavailable:
            pass
        else:
            raise AssertionError("retry exhaustion must fail")
    finally:
        asyncio.sleep = original_sleep
    assert session.retries == 2
    assert orchestrator.tasks[1].count_tool_calls == 0


def test_finalization_retry_returns_validated_json(tmp_path: Path):
    class FinalRetrySession(Session):
        async def final_send(self, messages):
            self.final_calls.append(messages)
            return answer("insufficient_system_resource", content="temporary")

        async def retry_send(self):
            return answer("stop", content=FINAL_JSON)

    session = FinalRetrySession(answer("stop", content="draft"))
    orchestrator = make_orchestrator(Connector(session), Engine(), Validator())
    original_sleep = asyncio.sleep

    async def no_sleep(_delay):
        return None

    asyncio.sleep = no_sleep
    try:
        result = asyncio.run(orchestrator.run_task(input_data(tmp_path)))
    finally:
        asyncio.sleep = original_sleep
    assert result == FINAL_JSON
    assert len(session.final_calls) == 1


def test_run_task_clears_only_expired_done_tasks(tmp_path: Path):
    orchestrator = make_orchestrator(Connector(Session(answer("stop"))), Engine(), Validator())
    orchestrator.tasks = {
        10: SimpleNamespace(expire_time=9, status=TaskStatus.done),
        11: SimpleNamespace(expire_time=11, status=TaskStatus.done),
        12: SimpleNamespace(expire_time=9, status=TaskStatus.in_processing),
    }
    orchestrator._now = lambda: 10
    asyncio.run(orchestrator.run_task(input_data(tmp_path)))
    assert 10 not in orchestrator.tasks
    assert {11, 12}.issubset(orchestrator.tasks)
