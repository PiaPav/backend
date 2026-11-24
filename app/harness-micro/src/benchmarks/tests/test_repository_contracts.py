from pathlib import Path
import re
from typing import get_args

from benchmarks.config import load_config
from response_models.models import Issue, ToolName
from rules.rules_config import RULES_CONFIG
from tools_engine.registry import TOOL_REGISTRY


def test_baseline_tracks_production_tools_and_limits() -> None:
    config = load_config()
    baseline = config.baseline

    assert config.variants.toolsets["full"] == tuple(item.name.value for item in TOOL_REGISTRY)
    assert set(config.variants.toolsets["targeted"]) == set(config.variants.toolsets["full"]) - {ToolName.Get_Graph.value, ToolName.Get_Metrics.value}
    assert baseline.limits.max_tool_calls == RULES_CONFIG.max_tool_calls == 6
    assert baseline.limits.max_iterations == RULES_CONFIG.max_iterations == 8
    assert baseline.limits.max_start_context_size == RULES_CONFIG.max_start_context_size == 262_144
    assert baseline.limits.max_provider_retries == RULES_CONFIG.max_provider_retries == 4


def test_baseline_tracks_model_and_profile_assumptions() -> None:
    config = load_config()
    model = config.models.models[config.baseline.model]

    assert model.model == "deepseek-flash"
    assert config.variants.contexts["overview"].graph_profile == "aggregate.overview"
    assert config.variants.contexts["overview"].metrics_profile == "metrics.overview"
    assert set(config.baseline.required_graph_profiles) == {"canonical.full", "aggregate.overview"}
    assert set(config.baseline.required_metrics_profiles) == {"metrics.full", "metrics.overview"}


def test_variants_match_stage_one_plan_exactly() -> None:
    config = load_config()
    baseline = config.baseline

    assert baseline.context == "overview"
    assert baseline.toolset == "full"
    assert baseline.limits.max_tool_calls == 6
    assert {(item.id, item.tool_budget, item.toolset, item.context) for item in config.variants.variants} == {
        ("budget-2", 2, None, None),
        ("budget-4", 4, None, None),
        ("tools-targeted", None, "targeted", None),
        ("tools-without-source", None, "without_source", None),
        ("tools-without-relations", None, "without_relations", None),
        ("context-compact", None, None, "compact"),
        ("context-architecture", None, None, "architecture"),
    }


def test_severity_contract_matches_production_analysis() -> None:
    assert set(get_args(Issue.model_fields["severity"].annotation)) == {
        "critical", "high", "medium", "low",
    }


def test_tracked_benchmark_contracts_do_not_contain_obvious_secrets() -> None:
    benchmark_root = Path(__file__).resolve().parents[1]
    inspected = [
        *benchmark_root.glob("configs/*.yml"),
        *benchmark_root.glob("schemas/*.json"),
        *benchmark_root.glob("prompts/*.md"),
    ]
    secret_patterns = (
        re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
        re.compile(r"(?i)(?:api[_-]?key|token|secret)\s*:\s*(?!null\b|[A-Z][A-Z0-9_]*\b)[\"']?[^\s\"']+"),
    )

    for path in inspected:
        content = path.read_text(encoding="utf-8")
        assert not any(pattern.search(content) for pattern in secret_patterns), path

    assert (benchmark_root / "runs" / ".gitignore").read_text(encoding="utf-8").splitlines() == ["*", "!.gitignore"]
