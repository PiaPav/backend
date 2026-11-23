import asyncio
from pathlib import Path

from core_server.logic.orchestrator import Orchestrator
from core_server.models.task_models import HarnessInputData


class ContextCapturingOrchestrator(Orchestrator):
    def __init__(self):
        self.tasks = {}
        self.received = None

    async def run_loop(self, unique_id, graph_overview, metrics_overview, analysis_context):
        self.received = (unique_id, graph_overview, metrics_overview, analysis_context)
        return "result"


def test_orchestrator_builds_context_and_uses_overview_profiles(tmp_path: Path) -> None:
    graph = tmp_path / "graph.json"
    metrics = tmp_path / "metrics.json"
    graph.write_text("graph content", encoding="utf-8")
    metrics.write_text("metrics content", encoding="utf-8")
    data = HarnessInputData(
        7, {"aggregate.overview": graph}, {"metrics.overview": metrics},
        tmp_path / "index.json", "a" * 64, "b" * 64,
    )
    orchestrator = ContextCapturingOrchestrator()

    result = asyncio.run(orchestrator.run_task(data))

    unique_id, graph_content, metrics_content, context = orchestrator.received
    assert result == "result"
    assert unique_id == context.task_id == 7
    assert graph_content == "graph content"
    assert metrics_content == "metrics content"
    assert context.graph_fingerprint == "a" * 64
    assert context.project_fingerprint == "b" * 64
