from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


@dataclass
class HarnessInputData:
    unique_id: int
    graph_path: Path
    metrics_path: Path
    source_index_path: Path


class TaskStatus(StrEnum):
    accept = "ACCEPT"
    in_processing = "IN_PROCESSING"
    done = "DONE"


@dataclass
class TaskInfo:
    unique_id: int
    current_iteration: int
    expire_time: float
    status: TaskStatus
