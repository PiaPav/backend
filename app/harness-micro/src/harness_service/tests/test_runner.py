import asyncio
from pathlib import Path
from harness_service.harness_runner import HarnessRequest, HarnessRunner


class Core:
    def __init__(self, error=None):
        self.error = error

    async def run_task(self, data):
        self.data = data
        if self.error:
            raise self.error
        return "result"


def request():
    return HarnessRequest(
        "tenant-1", "event-1", {"canonical.full": Path("graph")},
        {"metrics.full": Path("metrics")}, Path("index"), "g" * 64, "p" * 64,
    )


def test_runner_only_maps_request_and_returns_result() -> None:
    core = Core()
    runner = HarnessRunner(core, concurrency=1, timeout_seconds=1)

    result = asyncio.run(runner.execute(request()))

    assert result.content == "result"
    assert core.data.graph_profiles == {"canonical.full": Path("graph")}
    assert core.data.metrics_profiles == {"metrics.full": Path("metrics")}
    assert core.data.graph_fingerprint == "g" * 64
    assert core.data.project_fingerprint == "p" * 64


def test_runner_propagates_core_failure_without_lifecycle_access() -> None:
    core = Core(RuntimeError("provider failed"))
    runner = HarnessRunner(core, concurrency=1, timeout_seconds=1)

    try:
        asyncio.run(runner.execute(request()))
    except RuntimeError as error:
        assert str(error) == "provider failed"
    else:
        raise AssertionError("runner must propagate the core error")



def test_task_id_is_tenant_scoped() -> None:
    first = HarnessRunner._make_task_id("tenant-1", "same-event")
    second = HarnessRunner._make_task_id("tenant-2", "same-event")

    assert first != second


def test_runner_enforces_timeout() -> None:
    class SlowCore(Core):
        async def run_task(self, data):
            await asyncio.sleep(60)

    core = SlowCore()
    runner = HarnessRunner(core, concurrency=1, timeout_seconds=0.001)

    try:
        asyncio.run(runner.execute(request()))
    except TimeoutError:
        pass
    else:
        raise AssertionError("runner must enforce timeout_seconds")
