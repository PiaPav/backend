from abc import ABC, abstractmethod

from gpt_work_dir.tests.project1.data.models import CreateData


class SomeInterface(ABC):

    @abstractmethod
    def create(self, create_data: CreateData):
        pass

    @abstractmethod
    def clear(self):
        pass