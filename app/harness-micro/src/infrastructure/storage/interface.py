from abc import ABC, abstractmethod


class S3Interface(ABC):

    @abstractmethod
    def __init__(self, endpoint_url: str, access_key: str, secret_key: str, bucket: str) -> None:
        pass

    @abstractmethod
    async def create(self, key: str, data: bytes) -> None:
        pass

    @abstractmethod
    async def read(self, key: str) -> bytes:
        pass

    @abstractmethod
    async def update(self, key: str, data: bytes) -> None:
        pass

    @abstractmethod
    async def delete(self, key: str) -> None:
        pass