"""Registry of explicitly supported data-view profiles."""
from __future__ import annotations

CANONICAL_FULL_ID = "canonical.full"
CANONICAL_FULL_VERSION = 1
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


def select_graph_profile(profile_id: object, profile_version: object) -> str:
    """Validate an exact graph profile and return its artifact kind."""
    if profile_id == CANONICAL_FULL_ID:
        expected_version = CANONICAL_FULL_VERSION
        artifact_kind = "canonical"
    elif profile_id == STRUCTURE_DECLARATIONS_ID:
        expected_version = STRUCTURE_DECLARATIONS_VERSION
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
    if profile_id != STRUCTURE_DECLARATIONS_ID:
        raise ValueError(f"Unsupported graph view profile {profile_id!r}")
    if type(profile_version) is not int or profile_version != STRUCTURE_DECLARATIONS_VERSION:
        raise ValueError(
            f"Unsupported version {profile_version!r} for graph view profile {profile_id!r}"
        )
    return {
        "kind": _STRUCTURE_DECLARATIONS_COMPLETENESS_KIND,
        "preserves": list(_STRUCTURE_DECLARATIONS_PRESERVES),
        "omits": list(_STRUCTURE_DECLARATIONS_OMITS),
    }


__all__ = [
    "CANONICAL_FULL_ID",
    "CANONICAL_FULL_VERSION",
    "STRUCTURE_DECLARATIONS_ID",
    "STRUCTURE_DECLARATIONS_VERSION",
    "profile_metadata",
    "select_graph_profile",
]
