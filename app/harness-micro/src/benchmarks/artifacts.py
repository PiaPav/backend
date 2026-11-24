"""Strict loading and staging of producer-owned benchmark exports."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import MappingProxyType
from typing import Mapping

import jsonschema


@dataclass(frozen=True, slots=True)
class ProducerMetadata:
    service: str
    version: str


@dataclass(frozen=True, slots=True)
class ArtifactDescriptor:
    path: Path
    sha256: str
    size_bytes: int
    schema_version: int


@dataclass(frozen=True, slots=True)
class SourceIndexDescriptor(ArtifactDescriptor):
    project_fingerprint: str


@dataclass(frozen=True, slots=True)
class ProducerArtifactBundle:
    root: Path
    producer: ProducerMetadata
    source_root: Path
    project_fingerprint: str
    graph_fingerprint: str
    graph_artifacts: Mapping[str, ArtifactDescriptor]
    metrics_artifacts: Mapping[str, ArtifactDescriptor]
    source_index: SourceIndexDescriptor
    parser_semantics_version: int = 7
    metrics_semantics_version: int = 4


@dataclass(frozen=True, slots=True)
class StagedArtifactBundle:
    root: Path
    producer: ProducerMetadata
    source_root: Path
    project_fingerprint: str
    graph_fingerprint: str
    graph_artifacts: Mapping[str, ArtifactDescriptor]
    metrics_artifacts: Mapping[str, ArtifactDescriptor]
    source_index: SourceIndexDescriptor
    parser_semantics_version: int = 7
    metrics_semantics_version: int = 4


def _link_like(path: Path) -> bool:
    if path.is_symlink():
        return True
    junction = getattr(path, "is_junction", None)
    if junction is not None and junction():
        return True
    return bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400)


def _regular_directory(path: Path, context: str) -> None:
    try:
        if _link_like(path) or not path.is_dir():
            raise ValueError(f"{context} must be an existing ordinary directory")
    except OSError as error:
        raise ValueError(f"cannot inspect {context}: {error}") from error


def _safe_string(value: object, context: str) -> str:
    if type(value) is not str or not value or any(ord(character) < 32 for character in value):
        raise ValueError(f"{context} must be a non-empty safe string")
    return value


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _contained_entry(root: Path, path: Path, context: str) -> Path:
    """Require an existing path and every component below root to be non-link-like."""
    resolved_root = root.resolve(strict=True)
    try:
        relative = path.relative_to(root)
    except ValueError as error:
        raise ValueError(f"{context} must be inside staged root") from error
    current = root
    for part in relative.parts:
        current = current / part
        try:
            if _link_like(current):
                raise ValueError(f"{context} must not contain link-like components")
        except OSError as error:
            raise ValueError(f"cannot inspect {context}: {error}") from error
    try:
        current.resolve(strict=True).relative_to(resolved_root)
    except (OSError, ValueError) as error:
        raise ValueError(f"{context} must remain inside staged root") from error
    return current


def _relative_path(value: object, context: str) -> PurePosixPath:
    if type(value) is not str:
        raise ValueError(f"{context} must be a string")
    path = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if (not value or "\\" in value or path.is_absolute() or windows.is_absolute() or
            windows.drive or value.startswith("//") or path.as_posix() != value or
            any(part in ("", ".", "..") for part in path.parts)):
        raise ValueError(f"{context} must be an exact relative POSIX path")
    return path


def _bundle_entry(root: Path, value: object, context: str) -> Path:
    relative = _relative_path(value, context)
    current = root
    for part in relative.parts:
        current = current / part
        try:
            if _link_like(current):
                raise ValueError(f"{context} must not contain link-like entries")
        except OSError as error:
            raise ValueError(f"cannot inspect {context}: {error}") from error
    try:
        current.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (OSError, ValueError) as error:
        raise ValueError(f"{context} must remain inside the bundle root") from error
    return current


def _tree_files(root: Path) -> list[Path]:
    _regular_directory(root, "source path")
    resolved_root = root.resolve(strict=True)
    pending = [root]
    files: list[Path] = []
    while pending:
        directory = pending.pop()
        try:
            children = list(directory.iterdir())
        except OSError as error:
            raise ValueError(f"cannot inspect source tree: {error}") from error
        for child in children:
            try:
                if _link_like(child):
                    raise ValueError("source tree must not contain link-like entries")
                child.resolve(strict=True).relative_to(resolved_root)
            except OSError as error:
                raise ValueError(f"cannot inspect source tree: {error}") from error
            except ValueError as error:
                raise ValueError("source entry must remain inside source tree") from error
            if child.is_dir():
                pending.append(child)
            elif child.is_file():
                files.append(child)
            else:
                raise ValueError("source tree entries must be ordinary files or directories")
    return files


def _verified(path: Path, expected_hash: str, expected_size: int, context: str) -> None:
    if type(expected_size) is not int or expected_size < 0:
        raise ValueError(f"{context}.size_bytes must be a nonnegative integer")
    try:
        if _link_like(path) or not path.is_file():
            raise ValueError(f"{context} must identify an ordinary file")
        content = path.read_bytes()
    except OSError as error:
        raise ValueError(f"cannot read {context}: {error}") from error
    if len(content) != expected_size or hashlib.sha256(content).hexdigest() != expected_hash:
        raise ValueError(f"{context} size or SHA-256 does not match manifest")


def _descriptor(root: Path, raw: Mapping[str, object], context: str) -> ArtifactDescriptor:
    path = _bundle_entry(root, raw["path"], f"{context}.path")
    descriptor = ArtifactDescriptor(path, str(raw["sha256"]), raw["size_bytes"], raw["schema_version"])  # type: ignore[arg-type]
    if type(descriptor.schema_version) is not int or descriptor.schema_version != 1:
        raise ValueError(f"{context}.schema_version must be 1")
    _verified(path, descriptor.sha256, descriptor.size_bytes, context)
    return descriptor


def load_artifact_bundle(manifest_path: Path) -> ProducerArtifactBundle:
    """Load and verify a local producer export; no provenance is inferred."""
    manifest_path = Path(manifest_path)
    root = manifest_path.parent
    _regular_directory(root, "bundle root")
    try:
        if _link_like(manifest_path) or not manifest_path.is_file():
            raise ValueError("manifest must be an ordinary file")
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        schema_path = Path(__file__).resolve().parent / "schemas" / "artifact_manifest.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(schema).validate(raw)
    except (OSError, UnicodeError, json.JSONDecodeError, jsonschema.ValidationError) as error:
        raise ValueError(f"invalid artifact manifest: {error}") from error
    if not isinstance(raw, dict):
        raise ValueError("invalid artifact manifest: expected object")
    for field in ("schema_version",):
        if type(raw[field]) is not int:
            raise ValueError(f"manifest.{field} must be an integer")
    graph = raw["graph_profiles"]
    metrics = raw["metrics_profiles"]
    source = raw["source"]
    index = raw["source_index"]
    assert isinstance(graph, dict) and isinstance(metrics, dict) and isinstance(source, dict) and isinstance(index, dict)
    for owner, field in ((graph, "parser_semantics_version"), (metrics, "metrics_semantics_version"), (index, "schema_version")):
        if type(owner[field]) is not int:
            raise ValueError(f"manifest.{field} must be an integer")
    source_root = _bundle_entry(root, source["path"], "source.path")
    source_files = _tree_files(source_root)
    graph_raw = graph["artifacts"]
    metrics_raw = metrics["artifacts"]
    assert isinstance(graph_raw, dict) and isinstance(metrics_raw, dict)
    if not {"canonical.full", "aggregate.overview"}.issubset(graph_raw):
        raise ValueError("graph_profiles.artifacts lacks required profiles")
    if not {"metrics.full", "metrics.overview"}.issubset(metrics_raw):
        raise ValueError("metrics_profiles.artifacts lacks required profiles")
    for profile in (*graph_raw, *metrics_raw):
        _safe_string(profile, "artifact profile ID")
    graph_artifacts = {key: _descriptor(root, value, f"graph_profiles.artifacts.{key}") for key, value in graph_raw.items()}
    metrics_artifacts = {key: _descriptor(root, value, f"metrics_profiles.artifacts.{key}") for key, value in metrics_raw.items()}
    index_base = _descriptor(root, index, "source_index")
    source_index = SourceIndexDescriptor(index_base.path, index_base.sha256, index_base.size_bytes,
                                         index_base.schema_version, str(index["project_fingerprint"]))
    all_artifacts = [item.path for item in (*graph_artifacts.values(), *metrics_artifacts.values())]
    if len(set(all_artifacts)) != len(all_artifacts) or source_index.path in all_artifacts:
        raise ValueError("declared artifact paths must be unique")
    source_set = set(source_files)
    if manifest_path in source_set or source_index.path in source_set or source_set.intersection(all_artifacts):
        raise ValueError("manifest and declared artifacts must be outside the source tree")
    if graph["graph_fingerprint"] != metrics["graph_fingerprint"]:
        raise ValueError("graph and metrics fingerprints differ")
    if source["project_fingerprint"] != index["project_fingerprint"]:
        raise ValueError("source and source-index fingerprints differ")
    producer = raw["producer"]
    assert isinstance(producer, dict)
    service = _safe_string(producer["service"], "producer.service")
    version = _safe_string(producer["version"], "producer.version")
    return ProducerArtifactBundle(
        root.resolve(strict=True), ProducerMetadata(service, version),
        source_root, str(source["project_fingerprint"]), str(graph["graph_fingerprint"]),
        MappingProxyType(graph_artifacts), MappingProxyType(metrics_artifacts), source_index,
    )


def _copy_file(source: Path, target: Path, descriptor: ArtifactDescriptor) -> ArtifactDescriptor:
    target.parent.mkdir(parents=True, exist_ok=True)
    if _link_like(source):
        raise ValueError("artifact became link-like during staging")
    with source.open("rb") as source_stream, target.open("xb") as target_stream:
        shutil.copyfileobj(source_stream, target_stream)
    _verified(target, descriptor.sha256, descriptor.size_bytes, "staged artifact")
    return ArtifactDescriptor(target, descriptor.sha256, descriptor.size_bytes, descriptor.schema_version)


def stage_artifact_bundle(bundle: ProducerArtifactBundle, destination: Path) -> StagedArtifactBundle:
    """Copy verified inputs into a new all-or-nothing staging directory."""
    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        raise ValueError("staging destination must not exist")
    _regular_directory(destination.parent, "staging parent")
    destination_candidate = destination.resolve(strict=False)
    bundle_root = bundle.root.resolve(strict=True)
    source_root = bundle.source_root.resolve(strict=True)
    if _inside(destination_candidate, bundle_root) or _inside(destination_candidate, source_root):
        raise ValueError("staging destination must be outside the producer bundle")
    temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}-", dir=destination.parent))
    try:
        staged_source = temporary / "source"
        staged_source.mkdir()
        for source_file in _tree_files(bundle.source_root):
            relative = source_file.relative_to(bundle.source_root)
            target = staged_source / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if _link_like(source_file):
                raise ValueError("source entry became link-like during staging")
            with source_file.open("rb") as source_stream, target.open("xb") as target_stream:
                shutil.copyfileobj(source_stream, target_stream)
        graph = {profile: _copy_file(item, temporary / "artifacts" / "graph" / f"{number}.bin", descriptor)
                 for number, (profile, descriptor) in enumerate(sorted(bundle.graph_artifacts.items()))
                 for item in (descriptor.path,)}
        metrics = {profile: _copy_file(item, temporary / "artifacts" / "metrics" / f"{number}.bin", descriptor)
                   for number, (profile, descriptor) in enumerate(sorted(bundle.metrics_artifacts.items()))
                   for item in (descriptor.path,)}
        index_base = _copy_file(bundle.source_index.path, temporary / "artifacts" / "source-index.bin", bundle.source_index)
        source_index = SourceIndexDescriptor(index_base.path, index_base.sha256, index_base.size_bytes,
                                              index_base.schema_version, bundle.project_fingerprint)
        staged = StagedArtifactBundle(temporary, bundle.producer, staged_source,
                                      bundle.project_fingerprint, bundle.graph_fingerprint,
                                      MappingProxyType(graph), MappingProxyType(metrics), source_index)
        validate_staged_bundle(staged)
        temporary.rename(destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise

    graph = {key: ArtifactDescriptor(destination / value.path.relative_to(temporary), value.sha256,
                                     value.size_bytes, value.schema_version)
             for key, value in graph.items()}
    metrics = {key: ArtifactDescriptor(destination / value.path.relative_to(temporary), value.sha256,
                                       value.size_bytes, value.schema_version)
               for key, value in metrics.items()}
    source_index = SourceIndexDescriptor(destination / source_index.path.relative_to(temporary), source_index.sha256,
                                         source_index.size_bytes, source_index.schema_version,
                                         source_index.project_fingerprint)
    return StagedArtifactBundle(destination, bundle.producer, destination / "source",
                                bundle.project_fingerprint, bundle.graph_fingerprint,
                                MappingProxyType(graph), MappingProxyType(metrics), source_index)


def validate_staged_bundle(staged: StagedArtifactBundle) -> None:
    """Strictly revalidate containment and content of a staged bundle."""
    root = Path(staged.root)
    _regular_directory(root, "staged root")
    source_root = _contained_entry(root, Path(staged.source_root), "staged source root")
    _tree_files(source_root)
    _safe_string(staged.producer.service, "producer.service")
    _safe_string(staged.producer.version, "producer.version")
    if re.fullmatch(r"[0-9a-f]{64}", staged.project_fingerprint) is None:
        raise ValueError("staged project fingerprint changed")
    if re.fullmatch(r"[0-9a-f]{64}", staged.graph_fingerprint) is None:
        raise ValueError("staged graph fingerprint changed")
    if staged.parser_semantics_version != 7 or staged.metrics_semantics_version != 4:
        raise ValueError("staged semantics versions changed")
    if staged.source_index.project_fingerprint != staged.project_fingerprint:
        raise ValueError("staged source-index fingerprint changed")
    for group, descriptors in (("graph", staged.graph_artifacts), ("metrics", staged.metrics_artifacts)):
        for profile, descriptor in descriptors.items():
            _safe_string(profile, f"{group} profile ID")
            if descriptor.schema_version != 1:
                raise ValueError(f"staged {group} artifact schema version changed")
            path = _contained_entry(root, Path(descriptor.path), f"staged {group} artifact")
            _verified(path, descriptor.sha256, descriptor.size_bytes, f"staged {group} artifact")
    if staged.source_index.schema_version != 1:
        raise ValueError("staged source-index schema version changed")
    index_path = _contained_entry(root, Path(staged.source_index.path), "staged source index")
    _verified(index_path, staged.source_index.sha256, staged.source_index.size_bytes, "staged source index")


__all__ = ["ArtifactDescriptor", "ProducerArtifactBundle", "ProducerMetadata", "SourceIndexDescriptor",
           "StagedArtifactBundle", "load_artifact_bundle", "stage_artifact_bundle", "validate_staged_bundle"]
