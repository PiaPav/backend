from pathlib import Path
import shutil
from types import MappingProxyType

import pytest
import yaml

from benchmarks.config import load_config
from response_models.models import DeepseekModels


CONFIGS = Path(__file__).resolve().parents[1] / "configs"
SOURCE_ROOT = Path(__file__).resolve().parents[2]


def test_load_config_defaults() -> None:
    config = load_config()

    assert config.baseline.repeats == 5
    assert config.baseline.prompt.path == SOURCE_ROOT / "prompts" / "PROMPT.md"
    assert config.judge.prompt.path == SOURCE_ROOT / "benchmarks" / "prompts" / "judge.md"
    assert all(variant.repeats == 3 for variant in config.variants.variants)
    assert config.baseline.configuration_version == "1.0.0"
    assert config.variants.variants_version == "1.0.0"
    assert config.models.models_version == "1.0.0"
    assert config.judge.judge_config_version == "1.0.0"
    assert isinstance(config.variants.contexts, MappingProxyType)
    assert isinstance(config.variants.toolsets, MappingProxyType)
    assert isinstance(config.models.models, MappingProxyType)


def _copied_configs(tmp_path: Path) -> Path:
    target = tmp_path / "configs"
    shutil.copytree(CONFIGS, target)
    return target


def test_rejects_unknown_keys(tmp_path: Path) -> None:
    configs = _copied_configs(tmp_path)
    path = configs / "baseline.yml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["unexpected"] = True
    path.write_text(yaml.safe_dump(document), encoding="utf-8")

    with pytest.raises(ValueError, match="keys mismatch"):
        load_config(configs, SOURCE_ROOT)


@pytest.mark.parametrize("bad_value", [True, 0, -1, "3"])
def test_rejects_invalid_repeat_types_and_values(tmp_path: Path, bad_value: object) -> None:
    configs = _copied_configs(tmp_path)
    path = configs / "baseline.yml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["repeats"] = bad_value
    path.write_text(yaml.safe_dump(document), encoding="utf-8")

    with pytest.raises(ValueError, match="baseline.repeats"):
        load_config(configs, SOURCE_ROOT)


def test_rejects_prompt_digest_mismatch(tmp_path: Path) -> None:
    configs = _copied_configs(tmp_path)
    path = configs / "baseline.yml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["prompt"]["sha256"] = "0" * 64
    path.write_text(yaml.safe_dump(document), encoding="utf-8")

    with pytest.raises(ValueError, match="digest differs"):
        load_config(configs, SOURCE_ROOT)


def test_rejects_duplicate_and_multifactor_variants(tmp_path: Path) -> None:
    configs = _copied_configs(tmp_path)
    path = configs / "variants.yml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["variants"][1]["id"] = document["variants"][0]["id"]
    document["variants"][0]["context"] = "compact"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")

    with pytest.raises(ValueError, match="exactly one factor"):
        load_config(configs, SOURCE_ROOT)


def test_rejects_unknown_toolset_reference(tmp_path: Path) -> None:
    configs = _copied_configs(tmp_path)
    path = configs / "variants.yml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["variants"][2]["toolset"] = "missing"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")

    with pytest.raises(ValueError, match="unknown definition"):
        load_config(configs, SOURCE_ROOT)


def test_baseline_required_profiles_include_starting_overviews_and_full_profiles() -> None:
    baseline = load_config().baseline

    assert set(baseline.required_graph_profiles) == {"canonical.full", "aggregate.overview"}
    assert set(baseline.required_metrics_profiles) == {"metrics.full", "metrics.overview"}


def test_rejects_variant_tool_budget_above_baseline_ceiling(tmp_path: Path) -> None:
    configs = _copied_configs(tmp_path)
    path = configs / "variants.yml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["variants"][0]["tool_budget"] = 7
    path.write_text(yaml.safe_dump(document), encoding="utf-8")

    with pytest.raises(ValueError, match="tool_budget"):
        load_config(configs, SOURCE_ROOT)


def test_enabled_judge_requires_non_empty_url_and_model(tmp_path: Path) -> None:
    configs = _copied_configs(tmp_path)
    path = configs / "judge.yml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["judge"]["enabled"] = True
    path.write_text(yaml.safe_dump(document), encoding="utf-8")

    with pytest.raises(ValueError, match="judge.*url|url.*model"):
        load_config(configs, SOURCE_ROOT)


def test_analyzer_models_are_accepted_by_production_request_contract() -> None:
    config = load_config()

    for analyzer in config.models.models.values():
        assert analyzer.model in {model.value for model in DeepseekModels}


@pytest.mark.parametrize("file_name,version_field", [
    ("baseline.yml", "configuration_version"),
    ("variants.yml", "variants_version"),
    ("models.yml", "models_version"),
    ("judge.yml", "judge_config_version"),
])
def test_rejects_non_semver_configuration_versions(tmp_path: Path, file_name: str, version_field: str) -> None:
    configs = _copied_configs(tmp_path)
    path = configs / file_name
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document[version_field] = "version-one"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")

    with pytest.raises(ValueError, match="SemVer"):
        load_config(configs, SOURCE_ROOT)


@pytest.mark.parametrize("url", [
    "http://api.example/v1", "https://user:password@api.example/v1",
    "https://api.example/v1?token=x", "https://api.example/v1#fragment",
])
def test_rejects_unsafe_model_urls(tmp_path: Path, url: str) -> None:
    configs = _copied_configs(tmp_path)
    path = configs / "models.yml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["models"]["production-primary"]["url"] = url
    path.write_text(yaml.safe_dump(document), encoding="utf-8")

    with pytest.raises(ValueError, match="HTTPS URL"):
        load_config(configs, SOURCE_ROOT)


def test_rejects_invalid_api_key_environment_name(tmp_path: Path) -> None:
    configs = _copied_configs(tmp_path)
    path = configs / "judge.yml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["judge"]["api_key_env"] = "judge-api-key"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")

    with pytest.raises(ValueError, match="environment variable"):
        load_config(configs, SOURCE_ROOT)


@pytest.mark.parametrize("prompt_path", ["../outside.md", str((SOURCE_ROOT / "prompts" / "PROMPT.md").resolve())])
def test_rejects_prompt_paths_outside_source_root_or_absolute(tmp_path: Path, prompt_path: str) -> None:
    configs = _copied_configs(tmp_path)
    path = configs / "baseline.yml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["prompt"]["path"] = prompt_path
    path.write_text(yaml.safe_dump(document), encoding="utf-8")

    with pytest.raises(ValueError, match="relative|inside source_root"):
        load_config(configs, SOURCE_ROOT)
