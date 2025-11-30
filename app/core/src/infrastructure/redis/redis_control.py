from typing import Optional

import redis

from utils.config import CONFIG
from utils.logger import create_logger

log = create_logger("RedisConnector")


class RedisConnector(redis.asyncio.Redis):

    async def set_verification_code(self, key: str, code: int, expire_seconds: int = 60 * 5) -> bool:
        log.info(f"Вызов set_ver_code {key, code, expire_seconds}")
        await self.set(name=key, value=code, ex=expire_seconds)
        log.info(f"В Redis добавлен код верификации для {key}")
        return True

    async def get_verification_code(self, key: str) -> Optional[int]:
        code = await self.get(name=key)
        return int(code)

    async def delete_verification_code(self, key: str) -> bool:
        await self.delete(key)
        log.info(f"В Redis удален код верификации для {key}")
        return True


Redis = RedisConnector(host=CONFIG.redis.host, port=CONFIG.redis.port, db=CONFIG.redis.db, decode_responses=True)
