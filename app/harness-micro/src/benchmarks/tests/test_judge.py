import asyncio
import json
from pathlib import Path

import jsonschema

from benchmarks.config import JudgeConfig, PromptConfig
from benchmarks.evaluators.judge import consensus, evaluate_finding
from benchmarks.evaluators.judge_client import JudgeTechnicalResult


ROOT = Path(__file__).resolve().parents[1]


def _config(repeats: int = 3, threshold: float = 0.7) -> JudgeConfig:
    return JudgeConfig(1, "1.0.0", True, "https://judge.invalid", "judge", "KEY", 0.1, 2, 2, repeats, threshold, PromptConfig(ROOT / "prompts/judge.md", "0.1.0", "0" * 64, "uncalibrated"))


def _decision(verdict: str = "confirmed", confidence: float = 0.9, issue_id: str | None = "ISSUE-001", score: int = 2) -> dict[str, object]:
    return {"matched_issue_id": issue_id, "verdict": verdict, "category_score": score, "location_score": score, "evidence_score": score, "severity_score": score, "recommendation_score": score, "unsupported_claims": [], "confidence": confidence}


class Client:
    def __init__(self, results: list[JudgeTechnicalResult]) -> None:
        self.results = results
        self.messages: list[object] = []

    async def evaluate(self, messages: object) -> JudgeTechnicalResult:
        self.messages.append(messages)
        return self.results.pop(0)


def _result(decision: dict[str, object] | None, status: str = "completed") -> JudgeTechnicalResult:
    error = None
    if decision is None:
        from benchmarks.evaluators.judge_client import JudgeError
        error = JudgeError("transport_error", "TimeoutError")
    return JudgeTechnicalResult(status, decision, error, "judge", "id" if decision else None, {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None, "prompt_cache_hit_tokens": None, "prompt_cache_miss_tokens": None, "cost": None, "currency": None}, 0.01, 0)  # type: ignore[arg-type]


def test_exact_count_two_messages_and_minimal_payload() -> None:
    client = Client([_result(_decision()) for _ in range(3)])
    judged = asyncio.run(evaluate_finding(finding_index=4, finding={"title": "finding"}, candidate_expected_cards=[{"id": "ISSUE-001"}], relevant_evidence={"source": ["line"]}, system_prompt="rubric", config=_config(), client=client))  # type: ignore[arg-type]
    assert len(client.messages) == 3
    assert [item["evaluation_repeat"] for item in judged.envelopes] == [1, 2, 3]
    messages = client.messages[0]
    assert len(messages) == 2 and [item["role"] for item in messages] == ["system", "user"]  # type: ignore[index]
    payload = json.loads(messages[1]["content"])  # type: ignore[index]
    assert set(payload) == {"finding", "candidate_expected_cards", "relevant_evidence"}
    assert not ({"model", "config", "cost", "baseline"} & set(payload))


def test_envelopes_match_run_schema_contract() -> None:
    client = Client([_result(_decision())])
    judged = asyncio.run(evaluate_finding(finding_index=0, finding={}, candidate_expected_cards=[], relevant_evidence={}, system_prompt="rubric", config=_config(1), client=client))  # type: ignore[arg-type]
    assert judged.consensus.verdict == "confirmed"
    schema = json.loads((ROOT / "schemas" / "run_result.schema.json").read_text(encoding="utf-8"))
    judge_schema = json.loads((ROOT / "schemas" / "judge_result.schema.json").read_text(encoding="utf-8"))
    # Resolve the sole external reference without network access.
    envelope = json.loads(json.dumps(schema["$defs"]["judgeEnvelope"]).replace('"judge_result.schema.json"', '"#/$defs/localJudge"'))
    envelope["$defs"] = {"localJudge": judge_schema, "error": schema["$defs"]["error"], "usage": schema["$defs"]["usage"]}
    jsonschema.Draft202012Validator(envelope).validate(judged.envelopes[0])


def test_majority_medians_are_order_independent() -> None:
    items = [_result(_decision(score=0, confidence=0.8)).as_dict(), _result(_decision(score=2, confidence=1.0)).as_dict(), _result(_decision("unsupported", 0.1, None, 1)).as_dict()]
    first = consensus(items, 0.7, 3)
    second = consensus(list(reversed(items)), 0.7, 3)
    assert first == second
    assert first.verdict == "confirmed" and first.category_score == 1 and first.confidence == 0.8
    assert not first.requires_human_review


def test_human_review_for_errors_no_majority_novel_low_confidence_and_id_conflict() -> None:
    error = _result(None, "infrastructure_error").as_dict()
    cases = [
        ([_result(_decision()).as_dict(), _result(_decision()).as_dict(), error], 0.7, 3),
        ([_result(_decision()).as_dict(), _result(_decision("unsupported", issue_id=None)).as_dict()], 0.7, 2),
        ([_result(_decision("novel", issue_id=None)).as_dict()] * 2, 0.7, 2),
        ([_result(_decision(confidence=0.4)).as_dict()] * 2, 0.7, 2),
        ([_result(_decision(issue_id="ISSUE-001")).as_dict(), _result(_decision(issue_id="ISSUE-002")).as_dict()], 0.7, 2),
    ]
    assert all(consensus(items, threshold, count).requires_human_review for items, threshold, count in cases)
    assert consensus(cases[1][0], 0.7, 2).verdict is None


def test_abstain_majority_always_requires_human_review() -> None:
    items = [_result(_decision("abstain", issue_id=None)).as_dict() for _ in range(3)]
    result = consensus(items, 0.7, 3)
    assert result.verdict == "abstain"
    assert result.requires_human_review


def test_majority_threshold_uses_full_expected_count() -> None:
    completed = [_result(_decision()).as_dict() for _ in range(2)]
    errors = [_result(None, "infrastructure_error").as_dict() for _ in range(3)]
    result = consensus(completed + errors, 0.7, 5)
    assert result.verdict is None
    assert result.requires_human_review


def test_score_and_confidence_medians_use_all_completed_decisions() -> None:
    items = [
        _result(_decision("confirmed", 0.9, score=2)).as_dict(),
        _result(_decision("confirmed", 0.8, score=2)).as_dict(),
        _result(_decision("unsupported", 0.1, issue_id=None, score=0)).as_dict(),
    ]
    result = consensus(items, 0.0, 3)
    assert result.verdict == "confirmed"
    assert result.category_score == 2
    assert result.confidence == 0.8


def test_non_finite_direct_input_is_order_independent_and_never_forms_consensus() -> None:
    items = [
        _result(_decision(score=2)).as_dict(),
        _result(_decision(score=2)).as_dict(),
        _result(_decision(score=float("nan"))).as_dict(),
    ]
    first = consensus(items, 0.7, 3)
    second = consensus(list(reversed(items)), 0.7, 3)
    assert first == second
    assert first.verdict is None
    assert first.requires_human_review


def test_malformed_completed_results_return_empty_review_without_raising() -> None:
    malformed = [
        {key: value for key, value in _decision().items() if key != "confidence"},
        {**_decision(), "verdict": []},
        {**_decision(), "unsupported_claims": [["unhashable"]]},
        {**_decision(), "verdict": "unexpected"},
        {**_decision(), "matched_issue_id": "bad-id"},
        {**_decision(), "category_score": 3},
    ]
    valid = [_result(_decision()).as_dict(), _result(_decision()).as_dict()]

    for decision in malformed:
        result = consensus(valid + [_result(decision).as_dict()], 0.7, 3)
        assert result == type(result)(None, None, None, None, None, None, None, None, True)
