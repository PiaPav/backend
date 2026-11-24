"""Strict, side-effect-free loading of benchmark configuration files."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping
from urllib.parse import urlsplit

import yaml


_SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
_TOOLS = frozenset({
    "GET-CONTENT", "GET-CODE-RANGE", "GET-STRUCTURE", "FIND-GRAPH-NODES",
    "GET-GRAPH-NODE", "GET-METRICS-ITEM", "GET-GRAPH-SUBGRAPH",
    "GET-GRAPH-REFERENCES", "GET-GRAPH", "GET-METRICS",
})
_GRAPH_PROFILES = frozenset({
    "canonical.full", "aggregate.overview", "inventory.minimal", "aggregate.packages",
})
_METRICS_PROFILES = frozenset({
    "metrics.full", "metrics.overview", "metrics.aggregate", "metrics.architecture",
})
# Keep this immutable contract in sync with rules.rules_config.MAX_TOOL_CALLS_CEILING.
# Importing rules_config here would load its mutable production configuration.
_MAX_TOOL_CALLS_CEILING = 6


@dataclass(frozen=True, slots=True)
class PromptConfig:
    path: Path
    version: str
    sha256: str
    calibration_status: str | None = None


@dataclass(frozen=True, slots=True)
class LimitsConfig:
    max_tool_calls: int
    max_iterations: int
    max_start_context_size: int
    max_provider_retries: int
    timeout_seconds: int


@dataclass(frozen=True, slots=True)
class BaselineConfig:
    schema_version: int
    configuration_version: str
    configuration_id: str
    repeats: int
    model: str
    prompt: PromptConfig
    context: str
    toolset: str
    required_graph_profiles: tuple[str, ...]
    required_metrics_profiles: tuple[str, ...]
    limits: LimitsConfig
    temperature: float | None
    temperature_status: str


@dataclass(frozen=True, slots=True)
class ContextConfig:
    graph_profile: str
    metrics_profile: str


@dataclass(frozen=True, slots=True)
class VariantConfig:
    id: str
    repeats: int
    tool_budget: int | None
    toolset: str | None
    context: str | None


@dataclass(frozen=True, slots=True)
class VariantsConfig:
    schema_version: int
    variants_version: str
    contexts: Mapping[str, ContextConfig]
    toolsets: Mapping[str, tuple[str, ...]]
    variants: tuple[VariantConfig, ...]


@dataclass(frozen=True, slots=True)
class ModelConfig:
    url: str
    model: str
    api_key_env: str
    pricing: None


@dataclass(frozen=True, slots=True)
class ModelsConfig:
    schema_version: int
    models_version: str
    models: Mapping[str, ModelConfig]


@dataclass(frozen=True, slots=True)
class JudgeConfig:
    schema_version: int
    judge_config_version: str
    enabled: bool
    url: str | None
    model: str | None
    api_key_env: str
    temperature: float
    timeout_seconds: int
    max_transport_retries: int
    evaluations_per_finding: int
    confidence_threshold: float
    prompt: PromptConfig


@dataclass(frozen=True, slots=True)
class BenchmarkConfig:
    baseline: BaselineConfig
    variants: VariantsConfig
    models: ModelsConfig
    judge: JudgeConfig


def _mapping(value: object, name: str, keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or any(type(key) is not str for key in value):
        raise ValueError(f"{name} must be a mapping")
    unknown = set(value) - keys
    missing = keys - set(value)
    if unknown or missing:
        raise ValueError(f"{name} keys mismatch; missing={sorted(missing)}, unknown={sorted(unknown)}")
    return value


def _string(value: object, name: str) -> str:
    if type(value) is not str or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _integer(value: object, name: str, *, minimum: int = 1) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def _number(value: object, name: str, *, minimum: float, maximum: float) -> float:
    if type(value) not in (int, float) or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be a number between {minimum} and {maximum}")
    return float(value)


def _semver(value: object, name: str) -> str:
    version = _string(value, name)
    if not _SEMVER.fullmatch(version):
        raise ValueError(f"{name} must be SemVer")
    return version


def _url(value: object, name: str) -> str:
    url = _string(value, name)
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
        raise ValueError(f"{name} must be an HTTPS URL without credentials, query, or fragment")
    return url


def _env_name(value: object, name: str) -> str:
    result = _string(value, name)
    if not _ENV_NAME.fullmatch(result):
        raise ValueError(f"{name} must be an uppercase environment variable name")
    return result


def _prompt(value: object, name: str, source_root: Path) -> PromptConfig:
    data = _mapping(value, name, {"path", "version", "sha256", "calibration_status"} if name == "judge.prompt" else {"path", "version", "sha256"})
    version = _semver(data["version"], f"{name}.version")
    digest = _string(data["sha256"], f"{name}.sha256")
    if not _SEMVER.fullmatch(version) or not _SHA256.fullmatch(digest):
        raise ValueError(f"{name} has invalid SemVer or SHA-256")
    raw_path = Path(_string(data["path"], f"{name}.path"))
    if raw_path.is_absolute():
        raise ValueError(f"{name}.path must be relative")
    path = (source_root / raw_path).resolve()
    try:
        path.relative_to(source_root)
    except ValueError as exc:
        raise ValueError(f"{name}.path must remain inside source_root") from exc
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise ValueError(f"{name} file is missing or its digest differs")
    status = data.get("calibration_status")
    if status is not None:
        _string(status, f"{name}.calibration_status")
    return PromptConfig(path, version, digest, status)


def _read(path: Path) -> object:
    with path.open("r", encoding="utf-8") as stream:
        return yaml.safe_load(stream)


def load_config(config_dir: Path | None = None, source_root: Path | None = None) -> BenchmarkConfig:
    """Load all benchmark contracts. Paths default from this module, never CWD."""
    benchmark_root = Path(__file__).resolve().parent
    config_dir = (config_dir or benchmark_root / "configs").resolve()
    source_root = (source_root or benchmark_root.parent).resolve()

    raw = _mapping(_read(config_dir / "baseline.yml"), "baseline", {"schema_version", "configuration_version", "configuration_id", "repeats", "model", "prompt", "context", "toolset", "required_profiles", "limits", "temperature", "temperature_status"})
    profiles = _mapping(raw["required_profiles"], "baseline.required_profiles", {"graph", "metrics"})
    limits_raw = _mapping(raw["limits"], "baseline.limits", {"max_tool_calls", "max_iterations", "max_start_context_size", "max_provider_retries", "timeout_seconds"})
    limits = LimitsConfig(*(_integer(limits_raw[key], f"baseline.limits.{key}", minimum=0 if key == "max_provider_retries" else 1) for key in ("max_tool_calls", "max_iterations", "max_start_context_size", "max_provider_retries", "timeout_seconds")))
    if limits.max_tool_calls > _MAX_TOOL_CALLS_CEILING:
        raise ValueError(f"baseline.limits.max_tool_calls must not exceed {_MAX_TOOL_CALLS_CEILING}")
    baseline = BaselineConfig(
        _integer(raw["schema_version"], "baseline.schema_version"), _semver(raw["configuration_version"], "baseline.configuration_version"), _string(raw["configuration_id"], "baseline.configuration_id"),
        _integer(raw["repeats"], "baseline.repeats"), _string(raw["model"], "baseline.model"),
        _prompt(raw["prompt"], "baseline.prompt", source_root), _string(raw["context"], "baseline.context"),
        _string(raw["toolset"], "baseline.toolset"), tuple(_string_list(profiles["graph"], "baseline.required_profiles.graph")),
        tuple(_string_list(profiles["metrics"], "baseline.required_profiles.metrics")), limits,
        None if raw["temperature"] is None else _number(raw["temperature"], "baseline.temperature", minimum=0, maximum=2),
        _string(raw["temperature_status"], "baseline.temperature_status"),
    )

    vr = _mapping(_read(config_dir / "variants.yml"), "variants", {"schema_version", "variants_version", "contexts", "toolsets", "variants"})
    contexts: dict[str, ContextConfig] = {}
    for key, value in _plain_mapping(vr["contexts"], "variants.contexts").items():
        item = _mapping(value, f"contexts.{key}", {"graph_profile", "metrics_profile"})
        contexts[key] = ContextConfig(_string(item["graph_profile"], "graph_profile"), _string(item["metrics_profile"], "metrics_profile"))
    toolsets = {key: tuple(_string_list(value, f"toolsets.{key}")) for key, value in _plain_mapping(vr["toolsets"], "variants.toolsets").items()}
    if any(set(tools) - _TOOLS for tools in toolsets.values()):
        raise ValueError("toolsets contain an unknown production tool")
    if any(context.graph_profile not in _GRAPH_PROFILES or context.metrics_profile not in _METRICS_PROFILES for context in contexts.values()):
        raise ValueError("contexts contain an unknown benchmark profile")
    variants = []
    ids: set[str] = set()
    if not isinstance(vr["variants"], list):
        raise ValueError("variants.variants must be a list")
    for value in vr["variants"]:
        item = _mapping(value, "variant", {"id", "repeats", "tool_budget", "toolset", "context"})
        variant_id = _string(item["id"], "variant.id")
        changed = sum(item[key] is not None for key in ("tool_budget", "toolset", "context"))
        if variant_id in ids or changed != 1:
            raise ValueError("variant ids must be unique and exactly one factor must change")
        if item["toolset"] is not None and item["toolset"] not in toolsets or item["context"] is not None and item["context"] not in contexts:
            raise ValueError(f"variant {variant_id} references an unknown definition")
        tool_budget = None if item["tool_budget"] is None else _integer(item["tool_budget"], "variant.tool_budget")
        if tool_budget is not None and tool_budget > limits.max_tool_calls:
            raise ValueError(f"variant {variant_id} tool_budget must not exceed baseline.limits.max_tool_calls")
        ids.add(variant_id)
        variants.append(VariantConfig(variant_id, _integer(item["repeats"], "variant.repeats"), tool_budget, item["toolset"], item["context"]))
    variants_config = VariantsConfig(_integer(vr["schema_version"], "variants.schema_version"), _semver(vr["variants_version"], "variants.variants_version"), MappingProxyType(contexts), MappingProxyType(toolsets), tuple(variants))

    mr = _mapping(_read(config_dir / "models.yml"), "models", {"schema_version", "models_version", "models"})
    models = {}
    for key, value in _plain_mapping(mr["models"], "models.models").items():
        item = _mapping(value, f"models.{key}", {"url", "model", "api_key_env", "pricing"})
        if item["pricing"] is not None:
            raise ValueError("pricing must be null until verified")
        models[key] = ModelConfig(_url(item["url"], "model.url"), _string(item["model"], "model.model"), _env_name(item["api_key_env"], "model.api_key_env"), None)
    models_config = ModelsConfig(_integer(mr["schema_version"], "models.schema_version"), _semver(mr["models_version"], "models.models_version"), MappingProxyType(models))

    jr = _mapping(_read(config_dir / "judge.yml"), "judge document", {"schema_version", "judge_config_version", "judge"})
    item = _mapping(jr["judge"], "judge", {"enabled", "url", "model", "api_key_env", "temperature", "timeout_seconds", "max_transport_retries", "evaluations_per_finding", "confidence_threshold", "prompt"})
    if type(item["enabled"]) is not bool:
        raise ValueError("judge enabled/url/model have invalid types")
    judge_url = None if item["url"] is None else _url(item["url"], "judge.url")
    judge_model = None if item["model"] is None else _string(item["model"], "judge.model")
    if item["enabled"] and (judge_url is None or judge_model is None):
        raise ValueError("judge.url and judge.model must be non-empty strings when judge is enabled")
    judge = JudgeConfig(_integer(jr["schema_version"], "judge.schema_version"), _semver(jr["judge_config_version"], "judge.judge_config_version"), item["enabled"], judge_url, judge_model, _env_name(item["api_key_env"], "judge.api_key_env"), _number(item["temperature"], "judge.temperature", minimum=0, maximum=2), _integer(item["timeout_seconds"], "judge.timeout_seconds"), _integer(item["max_transport_retries"], "judge.max_transport_retries", minimum=0), _integer(item["evaluations_per_finding"], "judge.evaluations_per_finding"), _number(item["confidence_threshold"], "judge.confidence_threshold", minimum=0, maximum=1), _prompt(item["prompt"], "judge.prompt", source_root))

    if baseline.model not in models or baseline.context not in contexts or baseline.toolset not in toolsets:
        raise ValueError("baseline references an unknown model, context, or toolset")
    if set(baseline.required_graph_profiles) - _GRAPH_PROFILES or set(baseline.required_metrics_profiles) - _METRICS_PROFILES:
        raise ValueError("baseline requires an unknown profile")
    if any(version != 1 for version in (baseline.schema_version, variants_config.schema_version, models_config.schema_version, judge.schema_version)):
        raise ValueError("schema_version must be 1")
    if len(toolsets[baseline.toolset]) != len(set(toolsets[baseline.toolset])) or any(len(tools) != len(set(tools)) for tools in toolsets.values()):
        raise ValueError("toolsets must contain unique tools")
    return BenchmarkConfig(baseline, variants_config, models_config, judge)


def _plain_mapping(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(type(key) is not str or not key for key in value):
        raise ValueError(f"{name} must be a string-keyed mapping")
    return value


def _string_list(value: object, name: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a list")
    result = [_string(item, name) for item in value]
    if len(result) != len(set(result)):
        raise ValueError(f"{name} must contain unique values")
    return result
