"""Registry of explicitly supported data-view profiles."""
from __future__ import annotations

CANONICAL_FULL_ID = "canonical.full"
CANONICAL_FULL_VERSION = 1
INVENTORY_MINIMAL_ID = "inventory.minimal"
INVENTORY_MINIMAL_VERSION = 1
DEPENDENCY_FILES_ID = "dependency.files"
DEPENDENCY_FILES_VERSION = 1
STRUCTURE_DECLARATIONS_ID = "structure.declarations"
STRUCTURE_DECLARATIONS_VERSION = 1

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


__all__ = [
    "CANONICAL_FULL_ID",
    "CANONICAL_FULL_VERSION",
    "DEPENDENCY_FILES_ID",
    "DEPENDENCY_FILES_VERSION",
    "INVENTORY_MINIMAL_ID",
    "INVENTORY_MINIMAL_VERSION",
    "STRUCTURE_DECLARATIONS_ID",
    "STRUCTURE_DECLARATIONS_VERSION",
    "profile_metadata",
    "summary_profile_metadata",
    "select_graph_profile",
]
