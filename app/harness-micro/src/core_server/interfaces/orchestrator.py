from abc import ABC, abstractmethod
from pathlib import Path

from core_server.models.task_models import HarnessInputData
from llm_connector.interfaces.connector import LLMConnectorInterface
from llm_connector.interfaces.validator import ValidatorInterface
from tools_engine.interface.engine import EngineInterface


class OrchestratorInterface(ABC):

    @abstractmethod
    def __init__(self, llm_connector: LLMConnectorInterface, tools_engine: EngineInterface,
                 validator: ValidatorInterface):
        pass

    @abstractmethod
    async def start(self, url, apikey):
        """Запустить сервис"""
        pass

    @abstractmethod
    async def run_loop(self, unique_id: int, graph: str, metrix: str, index: Path) -> str:
        """Запустить цикл общения с ллм"""
        pass

    @abstractmethod
    async def run_task(self, data: HarnessInputData) -> str:
        """Запустить анализ"""
        pass
