from core_server.interfaces.core import CoreInterface
from core_server.interfaces.orchestrator import OrchestratorInterface
from core_server.models.task_models import HarnessInputData


class Core(CoreInterface):

    def __init__(self, orchestrator: OrchestratorInterface):
        self.orchestrator: OrchestratorInterface = orchestrator

    async def start(self, url, apikey):
        """Запустить систему"""
        await self.orchestrator.start(url, apikey)

    async def run_task(self, data: HarnessInputData) -> str:
        """Передать задачу ллм"""
        return await self.orchestrator.run_task(data)
