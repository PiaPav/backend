from abc import ABC, abstractmethod
from fastapi import UploadFile
from typing import AsyncIterator


class AbstractStorage(ABC):

    @abstractmethod
    async def upload_fileobj(self, key: str, fileobj: UploadFile) -> None:
        pass

    @abstractmethod
    async def delete_file(self, file_key: str) -> None:
        pass

    @abstractmethod
    async def upload_file_with_path(self, key: str, filepath: str)->None:
        pass
