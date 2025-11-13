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
    async def stream_upload(self, key: str, stream: AsyncIterator[bytes]) -> None:
        pass
