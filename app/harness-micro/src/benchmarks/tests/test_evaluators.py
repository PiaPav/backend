from pathlib import Path
from dataclasses import replace

from response_models.models import Issue, LLMAnalysis

from benchmarks.evaluators.deterministic import evaluate_deterministic
from benchmarks.evaluators.matcher import candidate_matches
from benchmarks.project import load_project


PROJECT = Path(__file__).resolve().parents[1] / "projects" / "import_cycle"


def _issue(**changes: object) -> Issue:
    values = {
        "title": "Circular Import found", "severity": "high",
        "description": "There is a dependency problem.", "location": "package_a/service.py",
        "evidence": "The modules import each other.", "recommendation": "Move the interface.",
    }
    values.update(changes)
    return Issue(**values)  # type: ignore[arg-type]


def test_matcher_requires_exact_location_and_meaning_but_not_recommendation() -> None:
    oracle = load_project(PROJECT)
    analysis = LLMAnalysis(issues=[
        _issue(),
        _issue(location="service.py"),
        _issue(title="Coupling", description="Dependency problem", evidence="Imports", recommendation="Remove circular import"),
        _issue(title="DEPENDENCY CYCLE detected", location="package_b/repository.py"),
    ], strengths=[])
    assert candidate_matches(analysis, oracle) == [
        {"finding_index": 0, "expected_issue_ids": ["ISSUE-001"]},
        {"finding_index": 1, "expected_issue_ids": []},
        {"finding_index": 2, "expected_issue_ids": []},
        {"finding_index": 3, "expected_issue_ids": ["ISSUE-001"]},
    ]


def test_matcher_can_return_multiple_ordered_candidates_for_one_issue() -> None:
    oracle = load_project(PROJECT)
    second = replace(oracle.expected_findings[0], id="ISSUE-002")
    oracle = replace(oracle, expected_findings=(oracle.expected_findings[0], second))
    assert candidate_matches(LLMAnalysis(issues=[_issue()], strengths=[]), oracle) == [
        {"finding_index": 0, "expected_issue_ids": ["ISSUE-001", "ISSUE-002"]},
    ]


def test_matcher_location_is_case_sensitive_while_meaning_is_casefolded() -> None:
    oracle = load_project(PROJECT)
    analysis = LLMAnalysis(issues=[
        _issue(title="CIRCULAR IMPORT"),
        _issue(title="CIRCULAR IMPORT", location="PACKAGE_A/service.py"),
    ], strengths=[])
    assert candidate_matches(analysis, oracle) == [
        {"finding_index": 0, "expected_issue_ids": ["ISSUE-001"]},
        {"finding_index": 1, "expected_issue_ids": []},
    ]


def test_deterministic_positive_case() -> None:
    result = evaluate_deterministic(LLMAnalysis(issues=[_issue()], strengths=[]), load_project(PROJECT))
    assert all(check["passed"] for check in result["checks"])
    assert result["violations"] == []


def test_deterministic_reports_stable_edge_case_violations() -> None:
    oracle = load_project(PROJECT)
    duplicate = _issue(severity="critical", location=None, evidence="Guaranteed Runtime Failure")
    analysis = LLMAnalysis(issues=[
        _issue(severity="low", location="package_a\\service.py"),
        duplicate,
        duplicate,
    ], strengths=[])
    result = evaluate_deterministic(analysis, oracle)
    assert [item["code"] for item in result["violations"]] == [
        "invalid_location",
        "forbidden_claim_lexical_match",
        "forbidden_claim_lexical_match",
        "exact_duplicate",
        "severity_order",
    ]
    assert result["violations"][-2]["finding_index"] == 2
    assert len(result["candidate_matches"]) == 3


def test_deterministic_output_is_repeatable_and_forbidden_scan_covers_all_text_fields() -> None:
    oracle = load_project(PROJECT)
    claim = "ALWAYS RAISES IMPORTERROR"
    issue = _issue(
        title=claim,
        description=claim,
        location=None,
        evidence=claim,
        recommendation=claim,
    )
    analysis = LLMAnalysis(issues=[issue], strengths=[])

    first = evaluate_deterministic(analysis, oracle)
    assert evaluate_deterministic(analysis, oracle) == first
    violations = first["violations"]
    assert [item["code"] for item in violations] == ["forbidden_claim_lexical_match"] * 4
    assert [item["finding_index"] for item in violations] == [0, 0, 0, 0]
