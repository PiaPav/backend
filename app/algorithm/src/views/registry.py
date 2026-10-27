"""Registry of explicitly supported data-view profiles."""
from __future__ import annotations

CANONICAL_FULL_ID = "canonical.full"
CANONICAL_FULL_VERSION = 1
INVENTORY_MINIMAL_ID = "inventory.minimal"
INVENTORY_MINIMAL_VERSION = 1
DEPENDENCY_FILES_ID = "dependency.files"
DEPENDENCY_FILES_VERSION = 1
DEPENDENCY_ARCHITECTURE_ID = "dependency.architecture"
DEPENDENCY_ARCHITECTURE_VERSION = 1
STRUCTURE_DECLARATIONS_ID = "structure.declarations"
STRUCTURE_DECLARATIONS_VERSION = 1
METRICS_OVERVIEW_ID = "metrics.overview"
METRICS_OVERVIEW_VERSION = 1
METRICS_ARCHITECTURE_ID = "metrics.architecture"
METRICS_ARCHITECTURE_VERSION = 1
METRICS_QUALITY_ID = "metrics.quality"
METRICS_QUALITY_VERSION = 1
METRICS_OBJECTS_ID = "metrics.objects"
METRICS_OBJECTS_VERSION = 1
CALLS_TOPOLOGY_ID = "calls.topology"
CALLS_TOPOLOGY_VERSION = 1
CALLS_DETAILED_ID = "calls.detailed"
CALLS_DETAILED_VERSION = 1
TYPES_TOPOLOGY_ID = "types.topology"
TYPES_TOPOLOGY_VERSION = 1
OBJECTS_METRICS_BASIS_ID = "objects.metrics_basis"
OBJECTS_METRICS_BASIS_VERSION = 1

_METRICS_PROFILES = {
    METRICS_OVERVIEW_ID: (
        METRICS_OVERVIEW_VERSION,
        "one_way_projection",
        (
            "activity_summary", "call_graph_summary", "dependency_graph_summary",
            "metric_population_semantics", "object_and_quality_population_counts",
            "project_size",
        ),
        (
            "architecture_details", "call_graph_rankings", "call_graph_topology_details",
            "code_quality_details", "dependency_graph_rankings", "object_oriented_details",
        ),
    ),
    METRICS_ARCHITECTURE_ID: (
        METRICS_ARCHITECTURE_VERSION,
        "query_lossless",
        (
            "architecture_metrics", "dependency_graph_metrics",
            "import_activity_counts", "metric_population_semantics",
            "package_grouping_semantics",
        ),
        (
            "call_graph_metrics", "code_quality_metrics", "non_import_activity_metrics",
            "object_oriented_metrics", "project_size",
        ),
    ),
    METRICS_QUALITY_ID: (
        METRICS_QUALITY_VERSION,
        "query_lossless",
        (
            "code_quality_metrics", "metric_population_semantics",
            "quality_threshold_semantics", "ranking_truncation_semantics",
        ),
        (
            "activity_metrics", "architecture_metrics", "call_graph_metrics",
            "dependency_graph_metrics", "object_oriented_metrics",
            "project_size_except_callable_counts",
        ),
    ),
    METRICS_OBJECTS_ID: (
        METRICS_OBJECTS_VERSION,
        "query_lossless",
        (
            "class_method_field_population_counts", "complete_object_oriented_metrics",
            "metric_population_semantics", "object_topology_interpretation_semantics",
            "ranking_truncation_semantics",
        ),
        (
            "activity_metrics", "architecture_metrics", "call_graph_metrics",
            "code_quality_metrics", "dependency_graph_metrics",
            "project_size_except_class_method_field_counts",
        ),
    ),
}

_STRUCTURE_DECLARATIONS_COMPLETENESS_KIND = "query_lossless"
_STRUCTURE_DECLARATIONS_PRESERVES = (
    "canonical_declaration_nodes",
    "canonical_declaration_ownership",
)
_STRUCTURE_DECLARATIONS_OMITS = (
    "call_relations",
    "callable_complexity_facts",
    "callsites",
    "diagnostics",
    "edge_locations",
    "field_access_relations",
    "import_references",
    "import_relations",
    "node_locations",
    "owner_structural_facts",
    "type_references",
    "type_relations",
)

_INVENTORY_MINIMAL_PRESERVES = (
    "canonical_root_descriptors",
    "diagnostic_kind_status_counts",
    "node_kind_counts",
    "reference_resolution_counts",
    "synthetic_method_count",
)
_INVENTORY_MINIMAL_OMITS = (
    "call_relations", "callable_complexity_facts", "callsite_details",
    "declaration_node_descriptors", "diagnostic_details", "edge_locations",
    "field_access_relations", "import_reference_details", "import_relations",
    "node_locations", "owner_structural_facts", "type_reference_details",
    "type_relations",
)

_DEPENDENCY_FILES_PRESERVES = (
    "canonical_root_descriptors",
    "exact_import_topology",
    "import_resolution_counts",
)
_DEPENDENCY_FILES_OMITS = (
    "call_relations",
    "callable_complexity_facts",
    "callsites",
    "declaration_nodes",
    "diagnostics",
    "edge_locations",
    "field_access_relations",
    "import_occurrence_details",
    "node_locations",
    "owner_structural_facts",
    "type_references",
    "type_relations",
)

_DEPENDENCY_ARCHITECTURE_PRESERVES = (
    "canonical_class_nodes",
    "canonical_class_ownership",
    "canonical_import_references",
    "canonical_root_descriptors",
    "exact_import_topology",
    "import_resolution_counts",
    "metrics_package_grouping_semantics",
)
_DEPENDENCY_ARCHITECTURE_OMITS = (
    "call_relations", "callable_complexity_facts", "callsites", "diagnostics",
    "edge_locations", "field_access_relations", "function_constant_method_field_nodes",
    "node_locations", "owner_structural_facts", "type_references", "type_relations",
)

_CALLS_TOPOLOGY_PRESERVES = (
    "callsite_resolution_awaited_counts",
    "canonical_callable_nodes",
    "canonical_callable_ownership",
    "exact_weighted_call_topology",
    "module_level_call_owner_population",
    "synthetic_method_identity",
)
_CALLS_TOPOLOGY_OMITS = (
    "callable_complexity_facts", "callsite_details", "class_kind", "diagnostics",
    "edge_locations", "field_access_relations", "import_references", "import_relations",
    "node_locations", "non_exact_call_topology", "owner_structural_facts",
    "type_references", "type_relations",
)

_CALLS_DETAILED_PRESERVES = (
    "call_activity_structural_basis",
    "call_graph_label_disambiguation_context",
    "callable_complexity_facts",
    "canonical_callable_nodes",
    "canonical_callable_ownership",
    "canonical_callsite_edge_correspondence",
    "canonical_callsites",
    "exact_weighted_call_topology",
    "module_level_call_owner_population",
    "synthetic_method_identity",
)
_CALLS_DETAILED_OMITS = (
    "class_kind", "diagnostics", "direct_import_occurrence_facts", "edge_locations",
    "field_access_relations", "field_and_constant_nodes", "import_references",
    "import_relations", "node_locations", "type_references", "type_relations",
)

_TYPES_TOPOLOGY_PRESERVES = (
    "canonical_class_and_field_nodes",
    "canonical_declaration_ownership",
    "canonical_type_references",
    "exact_type_topology",
)
_TYPES_TOPOLOGY_OMITS = (
    "call_relations", "callable_complexity_facts", "callsites", "class_kind",
    "constant_function_and_method_nodes", "diagnostics", "edge_locations",
    "field_access_relations", "import_references", "import_relations",
    "node_locations", "owner_structural_facts",
)

_OBJECTS_METRICS_BASIS_PRESERVES = (
    "call_weights_as_metadata",
    "canonical_class_field_method_populations",
    "canonical_declaration_ownership",
    "canonical_type_references",
    "exact_object_access_topology",
    "exact_object_call_topology",
    "exact_object_type_topology",
    "object_labels",
    "real_method_complexity",
    "synthetic_method_identity",
)
_OBJECTS_METRICS_BASIS_OMITS = (
    "callsites",
    "diagnostics",
    "import_references",
    "import_relations",
    "locations_outside_retained_complexity_and_type_references",
    "node_and_edge_locations",
    "non_metric_access_relations",
    "non_metric_call_relations",
    "owner_structural_facts",
    "unrelated_declarations_and_roots",
)


def select_graph_profile(profile_id: object, profile_version: object) -> str:
    """Validate an exact graph profile and return its artifact kind."""
    if profile_id == CANONICAL_FULL_ID:
        expected_version = CANONICAL_FULL_VERSION
        artifact_kind = "canonical"
    elif profile_id == INVENTORY_MINIMAL_ID:
        expected_version = INVENTORY_MINIMAL_VERSION
        artifact_kind = "graph_summary"
    elif profile_id == STRUCTURE_DECLARATIONS_ID:
        expected_version = STRUCTURE_DECLARATIONS_VERSION
        artifact_kind = "graph_view"
    elif profile_id == DEPENDENCY_FILES_ID:
        expected_version = DEPENDENCY_FILES_VERSION
        artifact_kind = "graph_view"
    elif profile_id == DEPENDENCY_ARCHITECTURE_ID:
        expected_version = DEPENDENCY_ARCHITECTURE_VERSION
        artifact_kind = "graph_view"
    elif profile_id == CALLS_TOPOLOGY_ID:
        expected_version = CALLS_TOPOLOGY_VERSION
        artifact_kind = "graph_view"
    elif profile_id == CALLS_DETAILED_ID:
        expected_version = CALLS_DETAILED_VERSION
        artifact_kind = "graph_view"
    elif profile_id == TYPES_TOPOLOGY_ID:
        expected_version = TYPES_TOPOLOGY_VERSION
        artifact_kind = "graph_view"
    elif profile_id == OBJECTS_METRICS_BASIS_ID:
        expected_version = OBJECTS_METRICS_BASIS_VERSION
        artifact_kind = "graph_view"
    else:
        raise ValueError(f"Unsupported graph profile {profile_id!r}")
    if type(profile_version) is not int or profile_version != expected_version:
        raise ValueError(
            f"Unsupported version {profile_version!r} for graph profile {profile_id!r}"
        )
    return artifact_kind


def profile_metadata(profile_id: object, profile_version: object) -> dict[str, object]:
    """Return metadata only for an exact, supported profile selection."""
    if profile_id == STRUCTURE_DECLARATIONS_ID:
        expected_version = STRUCTURE_DECLARATIONS_VERSION
        kind = _STRUCTURE_DECLARATIONS_COMPLETENESS_KIND
        preserves = _STRUCTURE_DECLARATIONS_PRESERVES
        omits = _STRUCTURE_DECLARATIONS_OMITS
    elif profile_id == DEPENDENCY_FILES_ID:
        expected_version = DEPENDENCY_FILES_VERSION
        kind = "query_lossless"
        preserves = _DEPENDENCY_FILES_PRESERVES
        omits = _DEPENDENCY_FILES_OMITS
    elif profile_id == DEPENDENCY_ARCHITECTURE_ID:
        expected_version = DEPENDENCY_ARCHITECTURE_VERSION
        kind = "query_lossless"
        preserves = _DEPENDENCY_ARCHITECTURE_PRESERVES
        omits = _DEPENDENCY_ARCHITECTURE_OMITS
    elif profile_id == CALLS_TOPOLOGY_ID:
        expected_version = CALLS_TOPOLOGY_VERSION
        kind = "query_lossless"
        preserves = _CALLS_TOPOLOGY_PRESERVES
        omits = _CALLS_TOPOLOGY_OMITS
    elif profile_id == CALLS_DETAILED_ID:
        expected_version = CALLS_DETAILED_VERSION
        kind = "query_lossless"
        preserves = _CALLS_DETAILED_PRESERVES
        omits = _CALLS_DETAILED_OMITS
    elif profile_id == TYPES_TOPOLOGY_ID:
        expected_version = TYPES_TOPOLOGY_VERSION
        kind = "query_lossless"
        preserves = _TYPES_TOPOLOGY_PRESERVES
        omits = _TYPES_TOPOLOGY_OMITS
    elif profile_id == OBJECTS_METRICS_BASIS_ID:
        expected_version = OBJECTS_METRICS_BASIS_VERSION
        kind = "query_lossless"
        preserves = _OBJECTS_METRICS_BASIS_PRESERVES
        omits = _OBJECTS_METRICS_BASIS_OMITS
    else:
        raise ValueError(f"Unsupported graph view profile {profile_id!r}")
    if type(profile_version) is not int or profile_version != expected_version:
        raise ValueError(
            f"Unsupported version {profile_version!r} for graph view profile {profile_id!r}"
        )
    return {
        "kind": kind,
        "preserves": list(preserves),
        "omits": list(omits),
    }


def summary_profile_metadata(profile_id: object, profile_version: object) -> dict[str, object]:
    """Return fresh completeness metadata for inventory.minimal v1 only."""
    if profile_id != INVENTORY_MINIMAL_ID:
        raise ValueError(f"Unsupported graph summary profile {profile_id!r}")
    if type(profile_version) is not int or profile_version != INVENTORY_MINIMAL_VERSION:
        raise ValueError(
            f"Unsupported version {profile_version!r} for graph summary profile {profile_id!r}"
        )
    return {
        "kind": "one_way_projection",
        "preserves": list(_INVENTORY_MINIMAL_PRESERVES),
        "omits": list(_INVENTORY_MINIMAL_OMITS),
    }


def metrics_profile_metadata(profile_id: object, profile_version: object) -> dict[str, object]:
    """Return a fresh completeness descriptor for an exact Metrics profile."""
    if profile_id not in _METRICS_PROFILES:
        raise ValueError(f"Unsupported metrics profile {profile_id!r}")
    expected, kind, preserves, omits = _METRICS_PROFILES[profile_id]
    if type(profile_version) is not int or profile_version != expected:
        raise ValueError(
            f"Unsupported version {profile_version!r} for metrics profile {profile_id!r}"
        )
    return {"kind": kind, "preserves": list(preserves), "omits": list(omits)}


__all__ = [
    "CANONICAL_FULL_ID",
    "CANONICAL_FULL_VERSION",
    "CALLS_TOPOLOGY_ID", "CALLS_TOPOLOGY_VERSION",
    "CALLS_DETAILED_ID", "CALLS_DETAILED_VERSION",
    "TYPES_TOPOLOGY_ID", "TYPES_TOPOLOGY_VERSION",
    "OBJECTS_METRICS_BASIS_ID", "OBJECTS_METRICS_BASIS_VERSION",
    "DEPENDENCY_FILES_ID",
    "DEPENDENCY_FILES_VERSION",
    "DEPENDENCY_ARCHITECTURE_ID",
    "DEPENDENCY_ARCHITECTURE_VERSION",
    "INVENTORY_MINIMAL_ID",
    "INVENTORY_MINIMAL_VERSION",
    "STRUCTURE_DECLARATIONS_ID",
    "STRUCTURE_DECLARATIONS_VERSION",
    "METRICS_ARCHITECTURE_ID", "METRICS_ARCHITECTURE_VERSION",
    "METRICS_OVERVIEW_ID", "METRICS_OVERVIEW_VERSION",
    "METRICS_QUALITY_ID", "METRICS_QUALITY_VERSION",
    "METRICS_OBJECTS_ID", "METRICS_OBJECTS_VERSION",
    "metrics_profile_metadata",
    "profile_metadata",
    "summary_profile_metadata",
    "select_graph_profile",
]
