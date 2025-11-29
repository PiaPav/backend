import asyncio
import random
from utils.logger import create_logger

log = create_logger("Security")


class Security:
    @staticmethod
    async def generate_code(length: int = 4) -> int:
        """Метод для генерации кода"""
        try:
            left = 10**(length-1)
            right = 10 ** length - 1
            code = await asyncio.to_thread(random.randint, left, right)
            return code

        except Exception as e:
            log.error(f"Ошибка генерации кода: {e}")
            raise Exception(e)
