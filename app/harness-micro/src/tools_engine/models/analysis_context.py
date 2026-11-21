from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True, slots=True)
class AnalysisContext:
    task_id: int
    graph_profiles: Mapping[str, Path]
    metrics_profiles: Mapping[str, Path]
    source_index_path: Path
    graph_fingerprint: str
    project_fingerprint: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "graph_profiles", MappingProxyType(dict(self.graph_profiles))
        )
        object.__setattr__(
            self, "metrics_profiles", MappingProxyType(dict(self.metrics_profiles))
        )
