import asyncio
import hashlib
from dataclasses import dataclass
from pathlib import Path

from core_server.logic.core import Core
from core_server.models.task_models import HarnessInputData, TaskStatus


@dataclass(frozen=True, slots=True)
class HarnessRequest:
    event_id: str
    graph_path: Path
    metrics_path: Path
    source_index_path: Path


@dataclass(frozen=True, slots=True)
class HarnessResult:
    content: str


class HarnessRunner:
    """
    Адаптер над существующим Core.

    Ограничивает параллелизм, устанавливает timeout и гарантированно
    закрывает LLM-сессию.
    """

    def __init__(
        self,
        core: Core,
        *,
        concurrency: int = 2,
        timeout_seconds: float = 600.0,
    ) -> None:
        if concurrency < 1:
            raise ValueError("concurrency must be positive")

        self._core = core
        self._semaphore = asyncio.Semaphore(concurrency)
        self._timeout_seconds = timeout_seconds

    async def execute(self, request: HarnessRequest) -> HarnessResult:
        # В текущем Core идентификатор задачи — int.
        # После изменения Core лучше передавать event_id напрямую как str.
        task_id = self._make_task_id(request.event_id)

        input_data = HarnessInputData(
            unique_id=task_id,
            graph_path=request.graph_path,
            metrics_path=request.metrics_path,
            source_index_path=request.source_index_path,
        )

        async with self._semaphore:
            try:
                content = await asyncio.wait_for(
                    self._core.run_task(input_data),
                    timeout=self._timeout_seconds,
                )

                task = self._core.tasks.get(task_id)
                if task is not None:
                    task.status = TaskStatus.done

                return HarnessResult(content=content)

            finally:
                # Core.run_task() пока не закрывает созданную LLM-сессию.
                # После переноса cleanup внутрь Core этот блок можно удалить.
                if task_id in self._core.llm_connector.sessions:
                    await self._core.llm_connector.close_session(task_id)

    @staticmethod
    def _make_task_id(event_id: str) -> int:
        """
        Стабильный положительный 63-bit ID.

        Это временный compatibility layer для существующего Core.
        Идемпотентность должна основываться на полном event_id, а не на этом ID.
        """
        digest = hashlib.sha256(event_id.encode("utf-8")).digest()
        return int.from_bytes(digest[:8], "big") & ((1 << 63) - 1)