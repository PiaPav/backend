from abc import ABC, abstractmethod

from core_server.interfaces.orchestrator import OrchestratorInterface
from core_server.models.task_models import HarnessInputData


class CoreInterface(ABC):

    @abstractmethod
    def __init__(self, orchestrator: OrchestratorInterface):
        pass

    @abstractmethod
    async def start(self, url, apikey):
        """Запустить сервис"""
        pass

    @abstractmethod
    async def run_task(self, data: HarnessInputData):
        """Передать задачу ллм"""
        pass
