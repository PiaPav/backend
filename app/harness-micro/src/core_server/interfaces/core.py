from abc import ABC, abstractmethod

from core_server.models.task_models import HarnessInputData
from llm_connector.interfaces.connector import LLMConnectorInterface
from llm_connector.interfaces.validator import ValidatorInterface
from tools_engine.interface.engine import EngineInterface


class CoreInterface(ABC):

    @abstractmethod
    def __init__(self, llm_connector: LLMConnectorInterface, tools_engine: EngineInterface,
                 validator: ValidatorInterface):
        pass

    @abstractmethod
    def start(self, url, apikey):
        """Запустить сервис"""
        pass

    @abstractmethod
    def run_task(self, data: HarnessInputData):
        """Передать задачу ллм"""
        pass
