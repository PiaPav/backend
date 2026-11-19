import asyncio
import json
import logging
import sys
from typing import Any

from .db.logs_orm import HarnessLogs, LogData


class DBHandler(logging.Handler):
    """Асинхронная запись логов в PostgreSQL."""

    def __init__(self):
        super().__init__()
        self.queue = asyncio.Queue()
        self.worker_task = None

    def emit(self, record):
        try:
            message = json.loads(record.getMessage())

            data = LogData(
                unique_id=message["unique_id"],
                type=record.levelname,
                event=message["event"],
                description=message["description"],
            )

            # Запускаем worker при первом логе.
            if self.worker_task is None or self.worker_task.done():
                loop = asyncio.get_running_loop()
                self.worker_task = loop.create_task(self._worker())

            self.queue.put_nowait(data)

        except Exception:
            self.handleError(record)

    async def _worker(self):
        while True:
            data = await self.queue.get()

            try:
                await HarnessLogs.write_log(data)

            except Exception as exc:
                print(
                    f"Failed to save log to DB: {exc}",
                    file=sys.stdout,
                )

            finally:
                self.queue.task_done()

    async def flush_async(self):
        await self.queue.join()



class CustomLogger:
    """Обёртка над logging.Logger с удобным API для событий.

    В message всегда пишется JSON:
    {"unique_id": int, "event": str, "description": str}
    """

    def __init__(self, name: str, level: int = logging.INFO,
                 fmt: str = "HARNESS: %(asctime)s - %(name)s - %(levelname)s - %(message)s",
                 stream=sys.stdout):
        self._logger = logging.getLogger(name)
        self._logger.setLevel(level)
        self._logger.propagate = False

        # Хендлеры добавляем только один раз на базовый логгер,
        # иначе при повторном create_logger("X") они задвоятся.
        if not self._logger.handlers:
            console_handler = logging.StreamHandler(stream)
            console_handler.setFormatter(logging.Formatter(fmt))
            self._logger.addHandler(console_handler)
            self._logger.addHandler(DBHandler())

        # Ссылка на DBHandler, чтобы уметь flush_async()
        self._db_handler = next(
            (h for h in self._logger.handlers if isinstance(h, DBHandler)),
            None,
        )

    # ---- внутреннее ----
    def _log_event(self, level: int, unique_id: int, event: str,
                   description: str, **kwargs):
        msg = json.dumps(
            {"unique_id": unique_id, "event": event, "description": description},
            ensure_ascii=False,
        )
        # stacklevel=3: _log_event -> info -> вызывающий код
        self._logger.log(level, msg, stacklevel=3, **kwargs)

    # ---- публичный API ----
    def debug(self, unique_id: int, event: str, description: str, **kwargs):
        self._log_event(logging.DEBUG, unique_id, event, description, **kwargs)

    def info(self, unique_id: int, event: str, description: str, **kwargs):
        self._log_event(logging.INFO, unique_id, event, description, **kwargs)

    def warning(self, unique_id: int, event: str, description: str, **kwargs):
        self._log_event(logging.WARNING, unique_id, event, description, **kwargs)

    def error(self, unique_id: int, event: str, description: str, **kwargs):
        self._log_event(logging.ERROR, unique_id, event, description, **kwargs)

    def critical(self, unique_id: int, event: str, description: str, **kwargs):
        self._log_event(logging.CRITICAL, unique_id, event, description, **kwargs)

    def exception(self, unique_id: int, event: str, description: str, **kwargs):
        kwargs.setdefault("exc_info", True)
        self._log_event(logging.ERROR, unique_id, event, description, **kwargs)

    # ---- доступ к базовому логгеру и flush ----
    @property
    def base(self) -> logging.Logger:
        return self._logger

    async def flush_async(self):
        if self._db_handler is not None:
            await self._db_handler.flush_async()


def create_logger(name: str, level: int | str = logging.INFO,
                  fmt: str = "HARNESS: %(asctime)s - %(name)s - %(levelname)s - %(message)s",
                  stream=sys.stdout) -> CustomLogger:
    return CustomLogger(name, level, fmt=fmt, stream=stream)