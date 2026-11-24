"""Prepare staged harness input without invoking the harness or an LLM."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from benchmarks.artifacts import StagedArtifactBundle, load_artifact_bundle, stage_artifact_bundle
from benchmarks.event import HarnessEventIdentity, build_harness_start_event


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class PreparedHarnessInput:
    bundle: StagedArtifactBundle
    event: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "event", _freeze(self.event))

    def wire_event(self) -> dict[str, object]:
        """Return a fresh JSON-compatible event for transport to the handler."""
        event = _thaw(self.event)
        assert isinstance(event, dict)
        return event


def prepare_harness_input(manifest_path: Path, destination: Path,
                          identity: HarnessEventIdentity) -> PreparedHarnessInput:
    bundle = stage_artifact_bundle(load_artifact_bundle(manifest_path), destination)
    return PreparedHarnessInput(bundle, build_harness_start_event(bundle, identity))


__all__ = ["PreparedHarnessInput", "prepare_harness_input"]
