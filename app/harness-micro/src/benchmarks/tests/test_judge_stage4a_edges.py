import asyncio
import json
from pathlib import Path
from urllib import error

import jsonschema
import pytest
from referencing import Registry, Resource

from benchmarks.config import JudgeConfig, PromptConfig
from benchmarks.evaluators.judge import consensus, evaluate_finding
from benchmarks.evaluators.judge_client import JudgeTechnicalResult, LLMJudgeClient


ROOT = Path(__file__).resolve().parents[1]


def _config(*, retries: int = 1, repeats: int = 1) -> JudgeConfig:
    return JudgeConfig(
        1, "1.0.0", True, "https://judge.invalid", "judge", "TEST_JUDGE_KEY",
        0.1, 2, retries, repeats, 0.7,
        PromptConfig(ROOT / "prompts/judge.md", "0.1.0", "0" * 64, "uncalibrated"),
    )


def _decision() -> dict[str, object]:
    return {
        "matched_issue_id": "ISSUE-001", "verdict": "confirmed",
        "category_score": 2, "location_score": 2, "evidence_score": 3,
        "severity_score": 2, "recommendation_score": 2,
        "unsupported_claims": [], "confidence": 0.9,
    }


def _response() -> dict[str, object]:
    return {"id": "response-1", "choices": [{"message": {"content": json.dumps(_decision())}}]}


def _envelope(decision: dict[str, object] | None) -> dict[str, object]:
    status = "completed" if decision is not None else "infrastructure_error"
    return JudgeTechnicalResult(
        status, decision, None, "judge", "response-1" if decision else None,
        {}, 0.0, 0,  # type: ignore[arg-type]
    ).as_dict()


class Transport:
    def __init__(self, responses: list[object]) -> None:
        self.responses = responses
        self.calls = 0

    async def request(self, **_kwargs: object) -> dict[str, object]:
        self.calls += 1
        value = self.responses.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value  # type: ignore[return-value]


def _http_error(status: int) -> error.HTTPError:
    return error.HTTPError("https://judge.invalid", status, "failure", {}, None)


@pytest.mark.parametrize(
    ("status", "expected_calls", "expected_status"),
    [(400, 1, "infrastructure_error"), (408, 2, "completed"),
     (429, 2, "completed"), (500, 2, "completed"),
     (599, 2, "completed"), (600, 1, "infrastructure_error")],
)
def test_only_documented_http_statuses_are_retried(
    monkeypatch: pytest.MonkeyPatch, status: int, expected_calls: int, expected_status: str,
) -> None:
    monkeypatch.setenv("TEST_JUDGE_KEY", "secret")
    transport = Transport([_http_error(status), _response()])

    async def exercise() -> None:
        async with LLMJudgeClient(_config(), transport) as client:
            result = await client.evaluate([])
        assert result.status == expected_status

    asyncio.run(exercise())
    assert transport.calls == expected_calls


def test_constructor_does_not_read_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_read(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("constructor performed file I/O")

    monkeypatch.setattr(Path, "read_text", fail_read)
    LLMJudgeClient(_config(), Transport([]))


def test_envelope_validates_with_real_external_reference_resolution() -> None:
    class Client:
        async def evaluate(self, _messages: object):
            from benchmarks.evaluators.judge_client import JudgeTechnicalResult
            return JudgeTechnicalResult(
                "completed", _decision(), None, "judge", "response-1",
                {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None,
                 "prompt_cache_hit_tokens": None, "prompt_cache_miss_tokens": None,
                 "cost": None, "currency": None}, 0.0, 0,
            )

    judged = asyncio.run(evaluate_finding(
        finding_index=0, finding={}, candidate_expected_cards=[], relevant_evidence={},
        system_prompt="rubric", config=_config(), client=Client(),  # type: ignore[arg-type]
    ))
    run_schema = json.loads((ROOT / "schemas/run_result.schema.json").read_text(encoding="utf-8"))
    judge_schema = json.loads((ROOT / "schemas/judge_result.schema.json").read_text(encoding="utf-8"))
    registry = Registry().with_resource(judge_schema["$id"], Resource.from_contents(judge_schema))
    validator = jsonschema.Draft202012Validator(run_schema, registry=registry)
    validator.evolve(schema=run_schema["$defs"]["judgeEnvelope"]).validate(judged.envelopes[0])


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_provider_nonfinite_json_is_judge_error_without_retry(
    monkeypatch: pytest.MonkeyPatch, constant: str,
) -> None:
    monkeypatch.setenv("TEST_JUDGE_KEY", "secret")
    content = json.dumps(_decision()).replace("0.9", constant)
    transport = Transport([{"id": "response-1", "choices": [{"message": {"content": content}}]}])

    async def exercise() -> None:
        async with LLMJudgeClient(_config(retries=2), transport) as client:
            result = await client.evaluate([])
        assert result.status == "judge_error"
        assert result.transport_retries == 0

    asyncio.run(exercise())
    assert transport.calls == 1


def test_majority_uses_full_expected_count_and_winner_controls_matched_id() -> None:
    assert consensus([_envelope(None)], 0.7, 1).verdict is None

    decisions = [
        _envelope(_decision()),
        _envelope(_decision()),
        _envelope({**_decision(), "verdict": "unsupported", "matched_issue_id": None}),
        _envelope(None),
        _envelope(None),
    ]
    result = consensus(decisions, 0.7, 5)
    assert result.verdict is None

    winning = [
        _envelope({**_decision(), "confidence": 0.9, "category_score": 2}),
        _envelope({**_decision(), "confidence": 0.8, "category_score": 2}),
        _envelope({**_decision(), "verdict": "unsupported", "matched_issue_id": None,
                   "confidence": 0.1, "category_score": 0}),
    ]
    result = consensus(winning, 0.0, 3)
    assert result.matched_issue_id == "ISSUE-001"
    assert result.category_score == 2
    assert result.confidence == 0.8


@pytest.mark.parametrize("nonfinite", [float("nan"), float("inf"), float("-inf")])
def test_direct_nonfinite_input_never_forms_order_dependent_consensus(nonfinite: float) -> None:
    decisions = [
        _envelope(_decision()),
        _envelope(_decision()),
        _envelope({**_decision(), "confidence": nonfinite}),
    ]
    forward = consensus(decisions, 0.7, 3)
    reverse = consensus(list(reversed(decisions)), 0.7, 3)
    assert forward == reverse
    assert forward.verdict is None
    assert forward.requires_human_review
