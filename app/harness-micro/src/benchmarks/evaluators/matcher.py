"""Conservative candidate generation without verdict assignment."""

from response_models.models import LLMAnalysis

from benchmarks.project import ProjectOracle


def candidate_matches(analysis: LLMAnalysis, oracle: ProjectOracle) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for index, issue in enumerate(analysis.issues):
        searchable = (issue.title.casefold(), issue.description.casefold(), issue.evidence.casefold())
        matches = []
        for expected in oracle.expected_findings:
            location_matches = issue.location is not None and issue.location in expected.locations
            meaning_matches = any(
                meaning.casefold() in field for meaning in expected.acceptable_meanings for field in searchable
            )
            if location_matches and meaning_matches:
                matches.append(expected.id)
        result.append({"finding_index": index, "expected_issue_ids": matches})
    return result
