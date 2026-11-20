import asyncio
from pathlib import Path
from types import SimpleNamespace

from core_server.models.task_models import TaskStatus
from harness_service.harness_runner import HarnessRequest, HarnessRunner


class Connector:
    def __init__(self):
        self.sessions = {}
        self.closed = []

    async def close_session(self, task_id):
        self.closed.append(task_id)
        self.sessions.pop(task_id)


class Core:
    def __init__(self, error=None):
        self.error = error
        self.orchestrator = SimpleNamespace(tasks={}, llm_connector=Connector())

    async def run_task(self, data):
        task = SimpleNamespace(status=TaskStatus.accept)
        self.orchestrator.tasks[data.unique_id] = task
        self.orchestrator.llm_connector.sessions[data.unique_id] = object()
        if self.error:
            raise self.error
        return "result"


def request():
    return HarnessRequest("tenant-1", "event-1", Path("graph"), Path("metrics"), Path("index"))


def test_runner_uses_orchestrator_state_and_closes_session() -> None:
    core = Core()
    runner = HarnessRunner(core, concurrency=1, timeout_seconds=1)

    result = asyncio.run(runner.execute(request()))

    task_id = runner._make_task_id("tenant-1", "event-1")
    assert result.content == "result"
    assert core.orchestrator.tasks[task_id].status is TaskStatus.done
    assert core.orchestrator.llm_connector.closed == [task_id]
    assert core.orchestrator.llm_connector.sessions == {}


def test_runner_closes_session_when_core_fails() -> None:
    core = Core(RuntimeError("provider failed"))
    runner = HarnessRunner(core, concurrency=1, timeout_seconds=1)

    try:
        asyncio.run(runner.execute(request()))
    except RuntimeError as error:
        assert str(error) == "provider failed"
    else:
        raise AssertionError("runner must propagate the core error")

    task_id = runner._make_task_id("tenant-1", "event-1")
    assert core.orchestrator.llm_connector.closed == [task_id]


def test_task_id_is_tenant_scoped() -> None:
    first = HarnessRunner._make_task_id("tenant-1", "same-event")
    second = HarnessRunner._make_task_id("tenant-2", "same-event")

    assert first != second


def test_runner_times_out_and_closes_cancelled_session() -> None:
    class SlowCore(Core):
        async def run_task(self, data):
            task = SimpleNamespace(status=TaskStatus.accept)
            self.orchestrator.tasks[data.unique_id] = task
            self.orchestrator.llm_connector.sessions[data.unique_id] = object()
            await asyncio.sleep(60)

    core = SlowCore()
    runner = HarnessRunner(core, concurrency=1, timeout_seconds=0.001)

    try:
        asyncio.run(runner.execute(request()))
    except TimeoutError:
        pass
    else:
        raise AssertionError("runner must enforce timeout_seconds")

    task_id = runner._make_task_id("tenant-1", "event-1")
    assert core.orchestrator.tasks[task_id].status is TaskStatus.done
    assert core.orchestrator.llm_connector.closed == [task_id]
    assert core.orchestrator.llm_connector.sessions == {}
