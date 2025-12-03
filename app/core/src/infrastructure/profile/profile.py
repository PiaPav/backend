from functools import wraps

from pyinstrument import Profiler

from utils.logger import create_logger

log = create_logger("Profile")


def profile_time(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        profiler = Profiler()
        profiler.start()

        result = await func(*args, **kwargs)

        profiler.stop()
        log.info(profiler.output_text(unicode=True, color=True))

        return result
    return wrapper
