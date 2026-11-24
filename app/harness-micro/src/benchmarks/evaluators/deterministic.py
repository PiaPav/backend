"""Offline, stable checks for analyzer output."""

from pathlib import PurePosixPath

from response_models.models import LLMAnalysis

from benchmarks.evaluators.matcher import candidate_matches
from benchmarks.project import ProjectOracle


_SEVERITY = {"critical": 3, "high": 2, "medium": 1, "low": 0}


def _valid_location(location: str, oracle: ProjectOracle) -> bool:
    path = PurePosixPath(location)
    if (not location or "\\" in location or path.is_absolute() or
            any(part in ("", ".", "..") for part in path.parts) or path.as_posix() != location):
        return False
    project_root = (oracle.project_dir / "project").resolve()
    candidate = project_root.joinpath(*path.parts)
    try:
        candidate.resolve().relative_to(project_root)
    except (OSError, ValueError):
        return False
    return candidate.is_file()


def evaluate_deterministic(analysis: LLMAnalysis, oracle: ProjectOracle) -> dict[str, object]:
    violations: list[dict[str, object]] = []
    severities = []
    seen: set[tuple[object, ...]] = set()
    forbidden = tuple((finding.id, claim) for finding in oracle.expected_findings for claim in finding.forbidden_claims)
    for index, issue in enumerate(analysis.issues):
        if issue.location is not None and not _valid_location(issue.location, oracle):
            violations.append({"code": "invalid_location", "message": "location is not an exact existing relative POSIX project file", "finding_index": index})
        severities.append(_SEVERITY.get(issue.severity, -1))
        fields = (issue.title, issue.severity, issue.description, issue.location, issue.evidence, issue.recommendation)
        for field_name, value in zip(("title", "severity", "description", "location", "evidence", "recommendation"), fields):
            if isinstance(value, str):
                for issue_id, claim in forbidden:
                    if claim.casefold() in value.casefold():
                        violations.append({"code": "forbidden_claim_lexical_match", "message": f"literal casefold lexical signal for {issue_id} in {field_name}: {claim}", "finding_index": index})
        if fields in seen:
            violations.append({"code": "exact_duplicate", "message": "all six issue fields duplicate an earlier finding", "finding_index": index})
        seen.add(fields)
    if any(left < right for left, right in zip(severities, severities[1:])):
        violations.append({"code": "severity_order", "message": "issues are not sorted by descending severity", "finding_index": None})

    location_ok = not any(item["code"] == "invalid_location" for item in violations)
    severity_ok = not any(item["code"] == "severity_order" for item in violations) and all(rank >= 0 for rank in severities)
    forbidden_ok = not any(item["code"] == "forbidden_claim_lexical_match" for item in violations)
    duplicate_ok = not any(item["code"] == "exact_duplicate" for item in violations)
    checks = [
        {"name": "locations", "passed": location_ok, "details": None if location_ok else "one or more locations are invalid"},
        {"name": "severity_order", "passed": severity_ok, "details": None if severity_ok else "severity is invalid or not descending"},
        {"name": "forbidden_claims", "passed": forbidden_ok, "details": None if forbidden_ok else "literal forbidden claim lexical signal found"},
        {"name": "exact_duplicates", "passed": duplicate_ok, "details": None if duplicate_ok else "duplicate issue found"},
    ]
    return {"checks": checks, "candidate_matches": candidate_matches(analysis, oracle), "violations": violations}
