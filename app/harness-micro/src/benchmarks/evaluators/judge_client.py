"""Side-effect-free asynchronous client for the benchmark judge."""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Mapping, Protocol, Sequence
from urllib import error, request

import jsonschema

from benchmarks.config import JudgeConfig


_EMPTY_USAGE = {
    "prompt_tokens": None, "completion_tokens": None, "total_tokens": None,
    "prompt_cache_hit_tokens": None, "prompt_cache_miss_tokens": None,
    "cost": None, "currency": None,
}


@lru_cache(maxsize=1)
def judge_result_validator() -> jsonschema.Draft202012Validator:
    """Load the local decision schema lazily and without remote resolution."""
    schema_path = Path(__file__).resolve().parents[1] / "schemas" / "judge_result.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


def is_valid_judge_result(value: object) -> bool:
    """Apply the canonical judge-result schema to an untrusted value."""
    try:
        judge_result_validator().validate(value)
    except Exception:
        return False
    return True


class AsyncJudgeTransport(Protocol):
    async def request(self, *, url: str, headers: Mapping[str, str], payload: Mapping[str, object], timeout: int) -> Mapping[str, Any]: ...


class _UrlLibTransport:
    async def request(self, *, url: str, headers: Mapping[str, str], payload: Mapping[str, object], timeout: int) -> Mapping[str, Any]:
        def send() -> Mapping[str, Any]:
            body = json.dumps(payload).encode("utf-8")
            req = request.Request(url, data=body, headers=dict(headers), method="POST")
            with request.urlopen(req, timeout=timeout) as response:
                value = json.loads(response.read().decode("utf-8"))
            if not isinstance(value, dict):
                raise ValueError("judge provider response must be an object")
            return value
        return await asyncio.to_thread(send)


@dataclass(frozen=True, slots=True)
class JudgeError:
    type: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"type": self.type, "message": self.message}


@dataclass(frozen=True, slots=True)
class JudgeTechnicalResult:
    status: Literal["completed", "judge_error", "infrastructure_error"]
    result: Mapping[str, object] | None
    error: JudgeError | None
    model: str | None
    response_id: str | None
    usage: Mapping[str, object]
    duration_seconds: float
    transport_retries: int

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status, "result": None if self.result is None else dict(self.result),
            "error": None if self.error is None else self.error.as_dict(), "model": self.model,
            "response_id": self.response_id, "usage": dict(self.usage),
            "duration_seconds": self.duration_seconds, "transport_retries": self.transport_retries,
        }


class LLMJudgeClient:
    """OpenAI-compatible judge client. Construction and import perform no I/O."""

    def __init__(self, config: JudgeConfig, transport: AsyncJudgeTransport | None = None) -> None:
        self._config = config
        self._transport = transport or _UrlLibTransport()
        self._api_key: str | None = None
        self._connected = False
        self._validator: jsonschema.Draft202012Validator | None = None

    def __repr__(self) -> str:
        return f"{type(self).__name__}(connected={self._connected})"

    async def connect(self) -> None:
        if not self._config.enabled or not self._config.url or not self._config.model:
            raise RuntimeError("judge is not fully configured and enabled")
        key = os.environ.get(self._config.api_key_env)
        if not key:
            raise RuntimeError("judge API key environment variable is missing")
        # Schema loading is delayed until explicit lifecycle entry.
        self._validator = judge_result_validator()
        self._api_key = key
        self._connected = True

    async def close(self) -> None:
        self._api_key = None
        self._connected = False

    async def __aenter__(self) -> LLMJudgeClient:
        await self.connect()
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        await self.close()

    async def evaluate(self, messages: Sequence[Mapping[str, str]]) -> JudgeTechnicalResult:
        if not self._connected or self._api_key is None or self._validator is None:
            raise RuntimeError("judge client is not connected")
        started = time.monotonic()
        retries = 0
        while True:
            try:
                raw = await self._transport.request(
                    url=self._config.url or "", headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
                    payload={"model": self._config.model or "", "temperature": self._config.temperature, "messages": list(messages), "response_format": {"type": "json_object"}},
                    timeout=self._config.timeout_seconds,
                )
                return self._parse_response(raw, started, retries)
            except error.HTTPError as exc:
                # Only throttling, timeout, and server responses are retryable;
                # ordinary 4xx responses are deterministic request failures.
                if (exc.code in (408, 429) or 500 <= exc.code <= 599) and retries < self._config.max_transport_retries:
                    retries += 1
                    continue
                return self._failure("infrastructure_error", "http_error", f"HTTP {exc.code}", started, retries)
            except (TimeoutError, ConnectionError, OSError, error.URLError) as exc:
                if retries < self._config.max_transport_retries:
                    retries += 1
                    continue
                return self._failure("infrastructure_error", "transport_error", type(exc).__name__, started, retries)
            except Exception as exc:
                return self._failure("infrastructure_error", "provider_error", type(exc).__name__, started, retries)

    def _parse_response(self, raw: Mapping[str, Any], started: float, retries: int) -> JudgeTechnicalResult:
        try:
            content = raw["choices"][0]["message"]["content"]
            decision = json.loads(content, parse_constant=_reject_json_constant)
            self._validator.validate(decision)  # type: ignore[union-attr]
            response_id = raw["id"]
            if not isinstance(response_id, str) or not response_id:
                raise ValueError("missing response id")
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError, jsonschema.ValidationError) as exc:
            return self._failure("judge_error", "invalid_judge_response", type(exc).__name__, started, retries)
        return JudgeTechnicalResult("completed", decision, None, self._config.model, response_id, _normalize_usage(raw.get("usage")), time.monotonic() - started, retries)

    def _failure(self, status: Literal["judge_error", "infrastructure_error"], kind: str, message: str, started: float, retries: int) -> JudgeTechnicalResult:
        return JudgeTechnicalResult(status, None, JudgeError(kind, message), self._config.model, None, dict(_EMPTY_USAGE), time.monotonic() - started, retries)


def _normalize_usage(value: object) -> dict[str, object]:
    result = dict(_EMPTY_USAGE)
    if not isinstance(value, dict):
        return result
    aliases = {
        "prompt_tokens": "prompt_tokens", "completion_tokens": "completion_tokens", "total_tokens": "total_tokens",
        "prompt_cache_hit_tokens": "prompt_cache_hit_tokens", "prompt_cache_miss_tokens": "prompt_cache_miss_tokens",
    }
    for source, target in aliases.items():
        item = value.get(source)
        if type(item) is int and item >= 0:
            result[target] = item
    details = value.get("prompt_tokens_details")
    if isinstance(details, dict) and type(details.get("cached_tokens")) is int and details["cached_tokens"] >= 0:
        result["prompt_cache_hit_tokens"] = details["cached_tokens"]
        if isinstance(result["prompt_tokens"], int):
            result["prompt_cache_miss_tokens"] = max(0, result["prompt_tokens"] - details["cached_tokens"])
    return result


def _reject_json_constant(value: str) -> object:
    raise ValueError(f"invalid JSON constant: {value}")
