from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from threading import RLock
from typing import Any, Callable, Mapping


@dataclass(frozen=True, slots=True)
class AnalysisContext:
    task_id: int
    graph_profiles: Mapping[str, Path]
    metrics_profiles: Mapping[str, Path]
    source_index_path: Path
    graph_fingerprint: str
    project_fingerprint: str
    _cache: dict[str, Any] = field(default_factory=dict, init=False, repr=False, compare=False)
    _cache_lock: RLock = field(default_factory=RLock, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "graph_profiles", MappingProxyType(dict(self.graph_profiles))
        )
        object.__setattr__(
            self, "metrics_profiles", MappingProxyType(dict(self.metrics_profiles))
        )

    def get_or_create_cached(self, key: str, factory: Callable[[], Any]) -> Any:
        with self._cache_lock:
            if key not in self._cache:
                self._cache[key] = factory()
            return self._cache[key]
