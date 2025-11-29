import redis
from utils.config import CONFIG

class RedisConnector(redis.asyncio.Redis):
    async def set_verification_code(self, key: str, code: int, expire_seconds: int = 60*5) -> bool:
        await self.set(name=key, value=code, ex=expire_seconds)
        return True

    async def check_verification_code(self, key: str) -> bool:
        code = await self.get(name=key)
        if code is None:
            return False
        return True

    async def delete_verification_code(self, key: str) -> bool:
        await self.delete(key)
        return True

Redis = RedisConnector(host=CONFIG.redis.host, port=CONFIG.redis.port, db=CONFIG.redis.db, decode_responses=True)