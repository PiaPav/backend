import asyncio
import json
from dataclasses import replace
from pathlib import Path

import pytest

from benchmarks.config import JudgeConfig, PromptConfig
from benchmarks.evaluators.judge_client import LLMJudgeClient


ROOT = Path(__file__).resolve().parents[1]


def _config(**changes: object) -> JudgeConfig:
    values = {
        "schema_version": 1, "judge_config_version": "1.0.0", "enabled": True,
        "url": "https://judge.invalid/v1/chat/completions", "model": "offline-judge",
        "api_key_env": "TEST_JUDGE_KEY", "temperature": 0.1, "timeout_seconds": 2,
        "max_transport_retries": 2, "evaluations_per_finding": 3, "confidence_threshold": 0.7,
        "prompt": PromptConfig(ROOT / "prompts" / "judge.md", "0.1.0", "0" * 64, "uncalibrated"),
    }
    values.update(changes)
    return JudgeConfig(**values)  # type: ignore[arg-type]


def _decision() -> dict[str, object]:
    return {
        "matched_issue_id": "ISSUE-001", "verdict": "confirmed", "category_score": 2,
        "location_score": 2, "evidence_score": 3, "severity_score": 2,
        "recommendation_score": 2, "unsupported_claims": [], "confidence": 0.9,
    }


class Transport:
    def __init__(self, responses: list[object]) -> None:
        self.responses = responses
        self.calls: list[dict[str, object]] = []

    async def request(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response  # type: ignore[return-value]


def _response(content: object) -> dict[str, object]:
    return {"id": "response-1", "choices": [{"message": {"content": content}}], "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}}


def test_lifecycle_is_explicit_and_key_is_private(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = Transport([_response(json.dumps(_decision()))])
    client = LLMJudgeClient(_config(), transport)
    assert repr(client) == "LLMJudgeClient(connected=False)"
    with pytest.raises(RuntimeError, match="not connected"):
        asyncio.run(client.evaluate([]))
    monkeypatch.setenv("TEST_JUDGE_KEY", "super-secret")

    async def exercise() -> None:
        async with client:
            result = await client.evaluate([{"role": "user", "content": "private prompt"}])
            assert result.status == "completed"
            assert result.usage["total_tokens"] == 10
            assert "super-secret" not in repr(result)
        with pytest.raises(RuntimeError, match="not connected"):
            await client.evaluate([])
    asyncio.run(exercise())
    assert "super-secret" not in repr(client)


def test_connect_fails_fast_for_disabled_or_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TEST_JUDGE_KEY", raising=False)
    with pytest.raises(RuntimeError, match="enabled"):
        asyncio.run(LLMJudgeClient(replace(_config(), enabled=False)).connect())
    with pytest.raises(RuntimeError, match="environment variable"):
        asyncio.run(LLMJudgeClient(_config()).connect())


def test_transport_errors_retry_but_invalid_json_and_schema_do_not(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_JUDGE_KEY", "secret")

    async def exercise() -> None:
        retrying = Transport([TimeoutError(), ConnectionError(), _response(json.dumps(_decision()))])
        async with LLMJudgeClient(_config(), retrying) as client:
            result = await client.evaluate([])
        assert result.status == "completed" and result.transport_retries == 2
        assert len(retrying.calls) == 3

        invalid_constant = json.dumps(_decision()).replace('"confidence": 0.9', '"confidence": NaN')
        for content in ("not-json", json.dumps({**_decision(), "confidence": 4}), invalid_constant):
            transport = Transport([_response(content)])
            async with LLMJudgeClient(_config(), transport) as client:
                result = await client.evaluate([])
            assert result.status == "judge_error" and result.transport_retries == 0
            assert result.result is None and len(transport.calls) == 1
    asyncio.run(exercise())


def test_error_and_result_never_contain_prompt_key_or_raw_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_JUDGE_KEY", "secret-value")
    transport = Transport([_response("private malformed payload")])

    async def exercise() -> None:
        async with LLMJudgeClient(_config(), transport) as client:
            result = await client.evaluate([{"role": "user", "content": "private prompt"}])
        rendered = repr(result.as_dict())
        assert "secret-value" not in rendered
        assert "private prompt" not in rendered
        assert "private malformed payload" not in rendered
    asyncio.run(exercise())
