from pathlib import Path

from tools_engine.models.analysis_context import AnalysisContext


def test_analysis_context_defensively_copies_read_only_profile_mappings() -> None:
    graph_profiles = {"canonical.full": Path("graph.json")}
    context = AnalysisContext(
        1, graph_profiles, {"metrics.full": Path("metrics.json")},
        Path("index.json"), "a" * 64, "b" * 64,
    )
    graph_profiles["other"] = Path("other.json")

    assert "other" not in context.graph_profiles
    try:
        context.graph_profiles["other"] = Path("other.json")
    except TypeError:
        pass
    else:
        raise AssertionError("profile mappings must be read-only")
