import asyncio
import random

from utils.logger import create_logger

log = create_logger("Security")


class Security:
    @staticmethod
    def _sync_generate_code(length: int = 4) -> int:
        """Синхронный метод для генерации кода"""
        try:
            left = 10 ** (length - 1)
            right = 10 ** length - 1
            code = random.randint(left, right)
            return code

        except Exception as e:
            log.error(f"Ошибка генерации кода: {e}")
            raise Exception(e)

    @staticmethod
    async def generate_code(length: int = 4) -> int:
        """Асинхронный метод генерации кода"""
        return await asyncio.to_thread(Security._sync_generate_code, length)
