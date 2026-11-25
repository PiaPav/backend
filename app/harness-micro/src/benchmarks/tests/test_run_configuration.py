from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pytest

from benchmarks.config import load_config
from benchmarks.runners import resolve_run_configuration, validate_required_profiles


def test_resolves_baseline_complete_effective_configuration() -> None:
    config = load_config()
    resolved = resolve_run_configuration(config, "baseline")

    assert resolved.configuration_id == "baseline"
    assert resolved.repeats == 5
    assert resolved.analyzer_id == "production-primary"
    assert resolved.analyzer_model == "deepseek-flash"
    assert resolved.context_id == "overview"
    assert (resolved.graph_profile_id, resolved.metrics_profile_id) == (
        "aggregate.overview", "metrics.overview")
    assert resolved.toolset_id == "full"
    assert resolved.tool_budget == resolved.limits.max_tool_calls == 6
    assert resolved.required_graph_profiles == ("canonical.full", "aggregate.overview")
    assert resolved.required_metrics_profiles == ("metrics.full", "metrics.overview")
    assert len(resolved.configuration_sha256) == 64


@pytest.mark.parametrize("configuration_id,field,expected", [
    ("budget-2", "tool_budget", 2),
    ("budget-4", "tool_budget", 4),
    ("tools-targeted", "toolset_id", "targeted"),
    ("tools-without-source", "toolset_id", "without_source"),
    ("tools-without-relations", "toolset_id", "without_relations"),
    ("context-compact", "context_id", "compact"),
    ("context-architecture", "context_id", "architecture"),
])
def test_resolves_every_variant_type_by_baseline_inheritance(
        configuration_id: str, field: str, expected: object) -> None:
    resolved = resolve_run_configuration(load_config(), configuration_id)

    assert getattr(resolved, field) == expected
    assert resolved.repeats == 3
    assert resolved.analyzer_id == "production-primary"


@pytest.mark.parametrize("configuration_id,graph_profile,metrics_profile", [
    ("context-compact", "inventory.minimal", "metrics.aggregate"),
    ("context-architecture", "aggregate.packages", "metrics.architecture"),
])
def test_context_variant_requires_only_mandatory_full_profiles_and_exact_start_pair(
        configuration_id: str, graph_profile: str, metrics_profile: str) -> None:
    resolved = resolve_run_configuration(load_config(), configuration_id)

    assert resolved.required_graph_profiles == ("canonical.full", graph_profile)
    assert resolved.required_metrics_profiles == ("metrics.full", metrics_profile)


def test_rejects_unknown_id_and_defensively_rejects_multifactor_variant() -> None:
    config = load_config()
    with pytest.raises(ValueError, match="unknown benchmark configuration ID"):
        resolve_run_configuration(config, "missing")

    bad = replace(config.variants.variants[0], context="compact")
    changed_variants = replace(config.variants, variants=(bad, *config.variants.variants[1:]))
    with pytest.raises(ValueError, match="exactly one factor"):
        resolve_run_configuration(replace(config, variants=changed_variants), bad.id)

    unchanged = replace(config.variants.variants[0], tool_budget=config.baseline.limits.max_tool_calls)
    changed_variants = replace(config.variants, variants=(unchanged, *config.variants.variants[1:]))
    with pytest.raises(ValueError, match="exactly one factor"):
        resolve_run_configuration(replace(config, variants=changed_variants), unchanged.id)


def test_rejects_variant_id_conflicting_with_baseline_even_when_baseline_requested() -> None:
    config = load_config()
    conflicting = replace(config.variants.variants[0], id=config.baseline.configuration_id)
    variants = replace(config.variants, variants=(conflicting, *config.variants.variants[1:]))

    with pytest.raises(ValueError, match="conflicts with the baseline"):
        resolve_run_configuration(replace(config, variants=variants), config.baseline.configuration_id)


def test_rejects_toolset_and_context_aliases_that_do_not_change_effective_values() -> None:
    config = load_config()

    tool_variant = replace(config.variants.variants[2], toolset="full-alias")
    toolsets = MappingProxyType({**config.variants.toolsets,
                                 "full-alias": config.variants.toolsets[config.baseline.toolset]})
    variants = replace(config.variants, toolsets=toolsets,
                       variants=(*config.variants.variants[:2], tool_variant,
                                 *config.variants.variants[3:]))
    with pytest.raises(ValueError, match="exactly one factor"):
        resolve_run_configuration(replace(config, variants=variants), tool_variant.id)

    context_variant = replace(config.variants.variants[-2], context="overview-alias")
    contexts = MappingProxyType({**config.variants.contexts,
                                 "overview-alias": config.variants.contexts[config.baseline.context]})
    variants = replace(config.variants, contexts=contexts,
                       variants=(*config.variants.variants[:-2], context_variant,
                                 config.variants.variants[-1]))
    with pytest.raises(ValueError, match="exactly one factor"):
        resolve_run_configuration(replace(config, variants=variants), context_variant.id)


def _bundle(graph: tuple[str, ...], metrics: tuple[str, ...]) -> SimpleNamespace:
    return SimpleNamespace(graph_artifacts={key: object() for key in graph},
                           metrics_artifacts={key: object() for key in metrics})


def test_profile_preflight_success() -> None:
    resolved = resolve_run_configuration(load_config(), "context-compact")
    validate_required_profiles(resolved, _bundle(resolved.required_graph_profiles,
                                                  resolved.required_metrics_profiles))


def test_effective_baseline_context_profiles_are_added_when_omitted_from_required() -> None:
    config = load_config()
    baseline = replace(config.baseline,
                       required_graph_profiles=("canonical.full",),
                       required_metrics_profiles=("metrics.full",))

    resolved = resolve_run_configuration(replace(config, baseline=baseline), baseline.configuration_id)

    assert resolved.required_graph_profiles == ("canonical.full", "aggregate.overview")
    assert resolved.required_metrics_profiles == ("metrics.full", "metrics.overview")
    validate_required_profiles(resolved, _bundle(resolved.required_graph_profiles,
                                                  resolved.required_metrics_profiles))


@pytest.mark.parametrize("missing_group,missing_id", [
    ("graph", "canonical.full"),
    ("graph", "inventory.minimal"),
    ("metrics", "metrics.full"),
    ("metrics", "metrics.aggregate"),
])
def test_profile_preflight_reports_each_missing_class_without_artifact_data(
        missing_group: str, missing_id: str) -> None:
    resolved = resolve_run_configuration(load_config(), "context-compact")
    graph = tuple(item for item in resolved.required_graph_profiles
                  if missing_group != "graph" or item != missing_id)
    metrics = tuple(item for item in resolved.required_metrics_profiles
                    if missing_group != "metrics" or item != missing_id)

    with pytest.raises(ValueError) as captured:
        validate_required_profiles(resolved, _bundle(graph, metrics))

    assert missing_id in str(captured.value)
    assert "/" not in str(captured.value) and "\\" not in str(captured.value)


def test_hash_is_deterministic_changes_with_effective_input_and_contains_no_secret(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "top-secret-value")
    config = load_config()
    first = resolve_run_configuration(config, "baseline")
    second = resolve_run_configuration(config, "baseline")
    changed = resolve_run_configuration(config, "budget-2")

    assert first.configuration_sha256 == second.configuration_sha256
    assert first.configuration_sha256 != changed.configuration_sha256
    assert "top-secret-value" not in repr(first.canonical_payload)
    assert first.api_key_env == "DEEPSEEK_API_KEY"


def test_prompt_checkout_path_is_not_part_of_canonical_identity() -> None:
    config = load_config()
    first = resolve_run_configuration(config, "baseline")
    moved_prompt = replace(config.baseline.prompt, path=Path("C:/other-checkout/private/prompt.md"))
    moved_config = replace(config, baseline=replace(config.baseline, prompt=moved_prompt))

    moved = resolve_run_configuration(moved_config, "baseline")

    assert first.canonical_payload == moved.canonical_payload
    assert first.configuration_sha256 == moved.configuration_sha256
    assert "PycharmProjects" not in repr(first.canonical_payload)
    assert "other-checkout" not in repr(moved.canonical_payload)


def test_result_and_nested_collections_are_immutable() -> None:
    resolved = resolve_run_configuration(load_config(), "baseline")

    assert isinstance(resolved.canonical_payload, MappingProxyType)
    assert isinstance(resolved.canonical_payload["configuration"], MappingProxyType)
    assert isinstance(resolved.canonical_payload["toolset"]["tools"], tuple)
    with pytest.raises(FrozenInstanceError):
        resolved.repeats = 1
    with pytest.raises(TypeError):
        resolved.canonical_payload["repeats"] = 1
    with pytest.raises(TypeError):
        resolved.canonical_payload["configuration"]["id"] = "changed"
