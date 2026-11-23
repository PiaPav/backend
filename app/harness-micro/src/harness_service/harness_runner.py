import asyncio
import hashlib
import math
from dataclasses import dataclass
from pathlib import Path

from core_server.logic.core import Core
from core_server.models.task_models import HarnessInputData


@dataclass(frozen=True, slots=True)
class HarnessRequest:
    tenant_id: str
    event_id: str
    graph_profiles: dict[str, Path]
    metrics_profiles: dict[str, Path]
    source_index_path: Path
    graph_fingerprint: str
    project_fingerprint: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "graph_profiles", dict(self.graph_profiles))
        object.__setattr__(self, "metrics_profiles", dict(self.metrics_profiles))


@dataclass(frozen=True, slots=True)
class HarnessResult:
    content: str


class HarnessRunner:
    """
    Адаптер над существующим Core.

    Ограничивает параллелизм и устанавливает общий timeout.
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
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be a finite positive number")

        self._core = core
        self._semaphore = asyncio.Semaphore(concurrency)
        self._timeout_seconds = timeout_seconds

    async def execute(self, request: HarnessRequest) -> HarnessResult:
        # Core is deliberately a thin facade.  Task/session ownership belongs
        # to the current Orchestrator implementation behind it.
        task_id = self._make_task_id(request.tenant_id, request.event_id)

        input_data = HarnessInputData(
            unique_id=task_id,
            graph_profiles=request.graph_profiles,
            metrics_profiles=request.metrics_profiles,
            source_index_path=request.source_index_path,
            graph_fingerprint=request.graph_fingerprint,
            project_fingerprint=request.project_fingerprint,
        )

        async with self._semaphore:
            content = await asyncio.wait_for(
                self._core.run_task(input_data),
                timeout=self._timeout_seconds,
            )
            return HarnessResult(content=content)

    @staticmethod
    def _make_task_id(tenant_id: str, event_id: str) -> int:
        """
        Стабильный положительный 63-bit ID.

        Это временный compatibility layer для существующего Core.
        Идемпотентность должна основываться на полном event_id, а не на этом ID.
        """
        digest = hashlib.sha256(f"{tenant_id}\0{event_id}".encode("utf-8")).digest()
        return (int.from_bytes(digest[:8], "big") & ((1 << 63) - 1)) or 1
