"""Deterministic public harness event construction."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from benchmarks.artifacts import (
    ArtifactDescriptor, StagedArtifactBundle, _contained_entry, validate_staged_bundle,
)


_UTC_RFC3339 = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z")


@dataclass(frozen=True, slots=True)
class HarnessEventIdentity:
    event_id: str
    occurred_at: str
    correlation_id: str
    causation_id: str
    tenant_id: str

    def __post_init__(self) -> None:
        for name in ("event_id", "occurred_at", "correlation_id", "causation_id", "tenant_id"):
            value = getattr(self, name)
            if type(value) is not str or not value or any(ord(character) < 32 for character in value):
                raise ValueError(f"{name} must be a non-empty safe string")
        if _UTC_RFC3339.fullmatch(self.occurred_at) is None:
            raise ValueError("occurred_at must be UTC RFC 3339")
        try:
            parsed = datetime.fromisoformat(self.occurred_at[:-1] + "+00:00")
        except ValueError as error:
            raise ValueError("occurred_at must be UTC RFC 3339") from error
        if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
            raise ValueError("occurred_at must be UTC RFC 3339")


def _artifact(root: Path, descriptor: ArtifactDescriptor) -> dict[str, object]:
    path = _contained_entry(root, descriptor.path, "staged artifact")
    try:
        junction = getattr(path, "is_junction", None)
        link_like = (path.is_symlink() or
                     (junction is not None and junction()) or
                     bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400))
        if link_like or not path.is_file():
            raise ValueError("staged artifact must be an ordinary file")
        content = path.read_bytes()
    except OSError as error:
        raise ValueError("cannot verify staged artifact") from error
    digest = hashlib.sha256(content).hexdigest()
    if len(content) != descriptor.size_bytes or digest != descriptor.sha256:
        raise ValueError("staged artifact size or SHA-256 changed")
    return {
        "uri": _contained_entry(root, path, "staged artifact").resolve(strict=True).as_uri(),
        "sha256": digest,
        "size_bytes": len(content),
        "schema_version": descriptor.schema_version,
    }


def build_harness_start_event(staged: StagedArtifactBundle,
                              identity: HarnessEventIdentity) -> dict[str, object]:
    """Build exactly the profile form of the public ``harness.start.v1`` contract."""
    validate_staged_bundle(staged)
    source_root = _contained_entry(staged.root, staged.source_root, "staged source root")
    return {
        "event_id": identity.event_id,
        "event_type": "harness.start.v1",
        "schema_version": 1,
        "occurred_at": identity.occurred_at,
        "correlation_id": identity.correlation_id,
        "causation_id": identity.causation_id,
        "tenant_id": identity.tenant_id,
        "producer": {"service": staged.producer.service, "version": staged.producer.version},
        "payload": {
            "source_uri": source_root.resolve(strict=True).as_uri(),
            "graph_profiles": {
                "parser_semantics_version": staged.parser_semantics_version,
                "graph_fingerprint": staged.graph_fingerprint,
                "artifacts": {key: _artifact(staged.root, value) for key, value in staged.graph_artifacts.items()},
            },
            "metrics_profiles": {
                "metrics_semantics_version": staged.metrics_semantics_version,
                "graph_fingerprint": staged.graph_fingerprint,
                "artifacts": {key: _artifact(staged.root, value) for key, value in staged.metrics_artifacts.items()},
            },
            "source_index": {
                **_artifact(staged.root, staged.source_index),
                "project_fingerprint": staged.source_index.project_fingerprint,
            },
        },
    }


__all__ = ["HarnessEventIdentity", "build_harness_start_event"]
