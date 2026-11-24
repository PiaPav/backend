"""Immutable benchmark-project oracle loading and semantic validation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import jsonschema
import yaml


@dataclass(frozen=True, slots=True)
class Evidence:
    nodes: tuple[str, ...]
    relations: tuple[str, ...]
    metrics: tuple[str, ...] = ()
    source: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RequiredData:
    graph: bool
    metrics: bool
    source: bool | str


@dataclass(frozen=True, slots=True)
class ExpectedFinding:
    id: str
    category: str
    severity_min: str
    severity_max: str
    locations: tuple[str, ...]
    evidence: Evidence
    acceptable_meanings: tuple[str, ...]
    required_data: RequiredData
    forbidden_claims: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProjectOracle:
    schema_version: int
    project_id: str
    project_version: str
    description: str
    expected_findings: tuple[ExpectedFinding, ...]
    additional_findings_policy: str
    project_dir: Path
    project_sha256: str


def _non_blank_strings(value: object, context: str = "benchmark") -> None:
    if isinstance(value, str) and not value.strip():
        raise ValueError(f"{context} contains a whitespace-only string")
    if isinstance(value, dict):
        for key, item in value.items():
            _non_blank_strings(item, f"{context}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _non_blank_strings(item, f"{context}[{index}]")


def _project_file(project_root: Path, location: str, context: str) -> Path:
    path = PurePosixPath(location)
    if (not location or "\\" in location or path.is_absolute() or
            any(part in ("", ".", "..") for part in path.parts) or path.as_posix() != location):
        raise ValueError(f"{context} must be an exact relative POSIX path")
    candidate = project_root.joinpath(*path.parts)
    try:
        candidate.resolve().relative_to(project_root.resolve())
    except (OSError, ValueError) as exc:
        raise ValueError(f"{context} must remain under the project directory") from exc
    if not candidate.is_file():
        raise ValueError(f"{context} does not identify a project file: {location}")
    return candidate


def _is_link_like(path: Path) -> bool:
    """Return whether *path* is a symlink or Windows reparse-point entry."""
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if is_junction is not None and is_junction():
        return True
    # st_file_attributes is only present on Windows. Checking the general
    # reparse flag also covers link-like objects unknown to pathlib.
    return bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400)


def _reject_link_like(path: Path, context: str) -> None:
    try:
        link_like = _is_link_like(path)
    except OSError as exc:
        raise ValueError(f"cannot inspect {context} {path}: {exc}") from exc
    if link_like:
        raise ValueError(f"{context} must not be a symlink, junction, or reparse point: {path}")


def _project_entries(project_root: Path) -> list[Path]:
    """Collect regular project files without traversing link-like entries."""
    _reject_link_like(project_root, "project directory")
    if not project_root.is_dir():
        raise ValueError(f"project directory does not exist: {project_root}")
    resolved_root = project_root.resolve(strict=True)
    files: list[Path] = []
    pending = [project_root]
    while pending:
        directory = pending.pop()
        try:
            children = list(directory.iterdir())
        except OSError as exc:
            raise ValueError(f"cannot inspect project directory {directory}: {exc}") from exc
        for child in children:
            _reject_link_like(child, "project entry")
            try:
                resolved = child.resolve(strict=True)
                resolved.relative_to(resolved_root)
            except (OSError, ValueError) as exc:
                raise ValueError(f"project entry must remain under the project directory: {child}") from exc
            if child.is_dir():
                pending.append(child)
            elif child.is_file():
                files.append(child)
    return files


def _digest(card: bytes, project_root: Path, project_files: list[Path]) -> str:
    digest = hashlib.sha256()
    entries = [("benchmark.yml", card)]
    resolved_root = project_root.resolve(strict=True)
    for path in project_files:
        _reject_link_like(path, "digest entry")
        try:
            path.resolve(strict=True).relative_to(resolved_root)
        except (OSError, ValueError) as exc:
            raise ValueError(f"digest entry must remain under the project directory: {path}") from exc
        entries.append((path.relative_to(project_root).as_posix(), path.read_bytes()))
    for name, content in sorted(entries, key=lambda item: item[0]):
        name_bytes = name.encode("utf-8")
        digest.update(len(name_bytes).to_bytes(8, "big"))
        digest.update(name_bytes)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def load_project(project_dir: Path) -> ProjectOracle:
    """Load one project card; this function is the module's only I/O entry point."""
    project_dir = Path(project_dir)
    _reject_link_like(project_dir, "benchmark project directory")
    if not project_dir.is_dir():
        raise ValueError(f"benchmark project directory does not exist: {project_dir}")
    project_dir = project_dir.resolve(strict=True)
    card_path = project_dir / "benchmark.yml"
    project_root = project_dir / "project"
    project_files = _project_entries(project_root)
    try:
        card_bytes = card_path.read_bytes()
        raw = yaml.safe_load(card_bytes)
        schema_path = Path(__file__).resolve().parent / "schemas" / "benchmark.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(schema).validate(raw)
    except (OSError, yaml.YAMLError, json.JSONDecodeError, jsonschema.ValidationError) as exc:
        raise ValueError(f"invalid benchmark card {card_path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"invalid benchmark card {card_path}: expected mapping")
    _non_blank_strings(raw)
    if raw["project_id"] != project_dir.name:
        raise ValueError("project_id must equal the project directory name")

    ranks = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    ids: set[str] = set()
    findings = []
    for index, item in enumerate(raw["expected_findings"]):
        context = f"expected_findings[{index}]"
        if item["id"] in ids:
            raise ValueError(f"{context}.id is duplicated: {item['id']}")
        ids.add(item["id"])
        if ranks[item["severity_min"]] > ranks[item["severity_max"]]:
            raise ValueError(f"{context} severity_min exceeds severity_max")
        for location in item["locations"]:
            _project_file(project_root, location, f"{context}.locations")
        evidence = item["evidence"]
        required = item["required_data"]
        has_graph = bool(evidence.get("nodes")) and bool(evidence.get("relations"))
        has_partial_graph = bool(evidence.get("nodes")) or bool(evidence.get("relations"))
        if required["graph"] is True and not has_graph:
            raise ValueError(f"{context}.required_data.graph=true requires evidence.graph")
        if required["graph"] is False and has_partial_graph:
            raise ValueError(f"{context}.required_data.graph=false contradicts evidence.graph")
        has_metrics = bool(evidence.get("metrics"))
        if required["metrics"] is True and not has_metrics:
            raise ValueError(f"{context}.required_data.metrics=true requires evidence.metrics")
        if required["metrics"] is False and has_metrics:
            raise ValueError(f"{context}.required_data.metrics=false contradicts evidence.metrics")
        has_source = bool(evidence.get("source"))
        if required["source"] is True and not has_source:
            raise ValueError(f"{context}.required_data.source=true requires evidence.source")
        if required["source"] is False and has_source:
            raise ValueError(f"{context}.required_data.source=false contradicts evidence.source")
        acceptable = tuple(item["acceptable_meanings"])
        for forbidden in item["forbidden_claims"]:
            if any(forbidden.casefold() in meaning.casefold() or meaning.casefold() in forbidden.casefold() for meaning in acceptable):
                raise ValueError(f"{context} forbidden claim overlaps acceptable meaning")
        findings.append(ExpectedFinding(
            item["id"], item["category"], item["severity_min"], item["severity_max"],
            tuple(item["locations"]), Evidence(tuple(evidence["nodes"]), tuple(evidence["relations"]),
            tuple(evidence.get("metrics", ())), tuple(evidence.get("source", ()))), acceptable,
            RequiredData(required["graph"], required["metrics"], required["source"]), tuple(item["forbidden_claims"]),
        ))
    return ProjectOracle(raw["schema_version"], raw["project_id"], raw["project_version"], raw["description"],
                          tuple(findings), raw["additional_findings_policy"], project_dir,
                          _digest(card_bytes, project_root, project_files))
