"""Supported Graph View projectors."""

from .dependency_files import project_dependency_files_v1
from .dependency_architecture import project_dependency_architecture_v1
from .structure_declarations import project_structure_declarations_v1
from .inventory_minimal import project_inventory_minimal_v1
from .metrics_architecture import project_metrics_architecture_v1
from .metrics_overview import project_metrics_overview_v1
from .calls_topology import project_calls_topology_v1

__all__ = [
    "project_dependency_architecture_v1", "project_dependency_files_v1", "project_inventory_minimal_v1",
    "project_structure_declarations_v1",
    "project_metrics_architecture_v1", "project_metrics_overview_v1",
    "project_calls_topology_v1",
]
