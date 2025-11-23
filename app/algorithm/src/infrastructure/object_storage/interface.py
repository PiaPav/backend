from abc import ABC, abstractmethod
from typing import AsyncIterator


class AbstractStorage(ABC):

    @abstractmethod
    async def stream_read(self, file_key: str) -> None:
        pass

    @abstractmethod
    async def read(self, file_key: str) -> None:
        pass

    @abstractmethod
    async def get_filenames(self, file_key: str) -> None:
        pass
