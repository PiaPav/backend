"""Resolve immutable, reproducible benchmark run configurations."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from benchmarks.artifacts import StagedArtifactBundle
from benchmarks.config import BenchmarkConfig, LimitsConfig, VariantConfig


def _ordered_union(first: tuple[str, ...], extra: str) -> tuple[str, ...]:
    return first if extra in first else (*first, extra)


def _replace_context_profile(required: tuple[str, ...], baseline_profile: str,
                             selected_profile: str) -> tuple[str, ...]:
    mandatory = tuple(dict.fromkeys(
        profile for profile in required if profile != baseline_profile))
    return _ordered_union(mandatory, selected_profile)


def _freeze_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    frozen: dict[str, object] = {}
    for key, item in value.items():
        if isinstance(item, Mapping):
            frozen[key] = _freeze_mapping(item)
        elif isinstance(item, list):
            frozen[key] = tuple(item)
        else:
            frozen[key] = item
    return MappingProxyType(frozen)


@dataclass(frozen=True, slots=True)
class ResolvedRunConfiguration:
    configuration_id: str
    baseline_configuration_id: str
    baseline_schema_version: int
    configuration_version: str
    variants_schema_version: int
    variants_version: str
    models_schema_version: int
    models_version: str
    repeats: int
    analyzer_id: str
    analyzer_model: str
    provider_url: str
    api_key_env: str
    prompt_path: Path
    prompt_version: str
    prompt_sha256: str
    context_id: str
    graph_profile_id: str
    metrics_profile_id: str
    toolset_id: str
    tools: tuple[str, ...]
    tool_budget: int
    limits: LimitsConfig
    temperature: float | None
    temperature_status: str
    required_graph_profiles: tuple[str, ...]
    required_metrics_profiles: tuple[str, ...]
    canonical_payload: Mapping[str, object]
    configuration_sha256: str


def _variant(config: BenchmarkConfig, configuration_id: str) -> VariantConfig | None:
    if any(item.id == config.baseline.configuration_id for item in config.variants.variants):
        raise ValueError("benchmark variant ID conflicts with the baseline configuration ID")
    if configuration_id == config.baseline.configuration_id:
        return None
    matches = [item for item in config.variants.variants if item.id == configuration_id]
    if len(matches) != 1:
        raise ValueError(f"unknown benchmark configuration ID: {configuration_id}")
    variant = matches[0]
    changed = sum(value is not None for value in (variant.tool_budget, variant.toolset, variant.context))
    if changed != 1:
        raise ValueError(f"benchmark variant {variant.id} must change exactly one factor")
    return variant


def resolve_run_configuration(config: BenchmarkConfig, configuration_id: str) -> ResolvedRunConfiguration:
    """Resolve baseline inheritance and produce a canonical non-secret run specification."""
    baseline = config.baseline
    variant = _variant(config, configuration_id)
    context_id = baseline.context if variant is None or variant.context is None else variant.context
    toolset_id = baseline.toolset if variant is None or variant.toolset is None else variant.toolset
    context = config.variants.contexts.get(context_id)
    baseline_context = config.variants.contexts.get(baseline.context)
    tools = config.variants.toolsets.get(toolset_id)
    baseline_tools = config.variants.toolsets.get(baseline.toolset)
    model = config.models.models.get(baseline.model)
    if (context is None or baseline_context is None or tools is None or baseline_tools is None or
            model is None):
        raise ValueError("run configuration references an unknown model, context, or toolset")
    changes_effective_value = variant is None or (
        (variant.tool_budget is not None and variant.tool_budget != baseline.limits.max_tool_calls) or
        (variant.toolset is not None and tuple(tools) != tuple(baseline_tools)) or
        (variant.context is not None and context != baseline_context)
    )
    if not changes_effective_value:
        raise ValueError(f"benchmark variant {variant.id} must change exactly one factor")
    tool_budget = (variant.tool_budget if variant is not None else None) or baseline.limits.max_tool_calls
    if tool_budget > baseline.limits.max_tool_calls:
        raise ValueError("run configuration tool budget exceeds the baseline limit")
    repeats = baseline.repeats if variant is None else variant.repeats
    required_graph = _replace_context_profile(
        baseline.required_graph_profiles, baseline_context.graph_profile, context.graph_profile)
    required_metrics = _replace_context_profile(
        baseline.required_metrics_profiles, baseline_context.metrics_profile, context.metrics_profile)

    payload: dict[str, object] = {
        "configuration": {
            "id": configuration_id, "baseline_id": baseline.configuration_id,
            "schema_version": baseline.schema_version, "version": baseline.configuration_version,
            "variants_schema_version": config.variants.schema_version,
            "variants_version": config.variants.variants_version,
            "models_schema_version": config.models.schema_version,
            "models_version": config.models.models_version,
        },
        "repeats": repeats,
        "analyzer": {"id": baseline.model, "model": model.model,
                     "provider": {"url": model.url, "api_key_env": model.api_key_env, "pricing": model.pricing}},
        "prompt": {"version": baseline.prompt.version, "sha256": baseline.prompt.sha256},
        "context": {"id": context_id, "graph_profile_id": context.graph_profile,
                    "metrics_profile_id": context.metrics_profile},
        "toolset": {"id": toolset_id, "tools": list(tools)},
        "tool_budget": tool_budget,
        "limits": {
            "max_tool_calls": baseline.limits.max_tool_calls,
            "max_iterations": baseline.limits.max_iterations,
            "max_start_context_size": baseline.limits.max_start_context_size,
            "max_provider_retries": baseline.limits.max_provider_retries,
            "timeout_seconds": baseline.limits.timeout_seconds,
        },
        "temperature": baseline.temperature,
        "temperature_status": baseline.temperature_status,
        "required_profiles": {"graph": list(required_graph), "metrics": list(required_metrics)},
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()
    return ResolvedRunConfiguration(
        configuration_id, baseline.configuration_id, baseline.schema_version, baseline.configuration_version,
        config.variants.schema_version, config.variants.variants_version, config.models.schema_version,
        config.models.models_version, repeats, baseline.model, model.model, model.url, model.api_key_env,
        baseline.prompt.path, baseline.prompt.version, baseline.prompt.sha256, context_id,
        context.graph_profile, context.metrics_profile, toolset_id, tuple(tools), tool_budget, baseline.limits,
        baseline.temperature, baseline.temperature_status, required_graph, required_metrics,
        _freeze_mapping(payload), digest,
    )


def validate_required_profiles(resolved: ResolvedRunConfiguration,
                               staged_bundle: StagedArtifactBundle) -> None:
    """Reject a staged bundle unless every exact effective profile ID is present."""
    missing_graph = [item for item in resolved.required_graph_profiles
                     if item not in staged_bundle.graph_artifacts]
    missing_metrics = [item for item in resolved.required_metrics_profiles
                       if item not in staged_bundle.metrics_artifacts]
    if missing_graph or missing_metrics:
        details = []
        if missing_graph:
            details.append(f"graph={missing_graph!r}")
        if missing_metrics:
            details.append(f"metrics={missing_metrics!r}")
        raise ValueError("staged bundle lacks required profiles: " + ", ".join(details))


__all__ = ["ResolvedRunConfiguration", "resolve_run_configuration", "validate_required_profiles"]
