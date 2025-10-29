from abc import ABC, abstractmethod
from fastapi import UploadFile


class AbstractStorage(ABC):

    @abstractmethod
    async def upload_fileobj(self, key: str, fileobj: UploadFile) -> None:
        pass

    @abstractmethod
    async def delete_file(self, file_key: str) -> None:
        pass
