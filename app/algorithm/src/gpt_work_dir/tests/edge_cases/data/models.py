from abc import ABC, abstractmethod


class Base(ABC):
    @abstractmethod
    def run(self):
        pass


class Middle(Base):
    pass


class Concrete(Middle):
    @staticmethod
    def helper(value: int = 1, *, enabled: bool = True) -> int:
        return value

    @classmethod
    def build(cls):
        return cls()

    @property
    def status(self):
        return True

    def run(self):
        return None
