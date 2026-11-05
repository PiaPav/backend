from abc import ABC, abstractmethod
from typing import Optional


class AbstractRedisConnector(ABC):

    @abstractmethod
    async def set_verification_code(self, key: str, code: int, expire_seconds: int = 60 * 5) -> bool:
        pass

    @abstractmethod
    async def get_verification_code(self, key: str) -> Optional[int]:
        pass

    @abstractmethod
    async def delete_verification_code(self, key: str) -> bool:
        pass

    @abstractmethod
    async def check_redis(self) -> None:
        pass
