from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


@dataclass
class HarnessInputData:
    unique_id: int
    graph_profiles: dict[str, Path]
    metrics_profiles: dict[str, Path]
    source_index_path: Path
    graph_fingerprint: str
    project_fingerprint: str

    def __post_init__(self) -> None:
        self.graph_profiles = dict(self.graph_profiles)
        self.metrics_profiles = dict(self.metrics_profiles)


class TaskStatus(StrEnum):
    accept = "ACCEPT"
    in_processing = "IN_PROCESSING"
    done = "DONE"


@dataclass
class TaskInfo:
    unique_id: int
    current_iteration: int
    expire_time: float
    count_tool_calls: int
    status: TaskStatus
