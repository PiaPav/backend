from abc import ABC, abstractmethod


class PromptsLoaderInterface(ABC):

    @abstractmethod
    def load_prompt(self) -> str:
        """Загрузить промт для нейронки"""
        pass
