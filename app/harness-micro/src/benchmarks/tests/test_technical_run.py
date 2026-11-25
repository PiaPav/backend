import asyncio
import hashlib
from contextlib import contextmanager
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from pathlib import Path

import pytest
import jsonschema
import json

from benchmarks.runners import (
    TechnicalCheck, TechnicalError, TechnicalRunEnvelope, TechnicalRunSpec,
    execute_technical_run,
)
from harness_service.harness_handler import MaterializedInputs
from harness_service.harness_runner import HarnessResult


def _event() -> dict[str, object]:
    descriptor = {"uri": "file:///offline", "sha256": "a" * 64, "size_bytes": 1,
                  "schema_version": 1}
    return {"event_id": "event-1", "event_type": "harness.start.v1", "schema_version": 1,
            "occurred_at": "2026-11-25T00:00:00Z", "correlation_id": "correlation-1",
            "causation_id": "cause-1", "tenant_id": "tenant-1",
            "producer": {"service": "offline", "version": "1"},
            "payload": {"source_uri": "file:///source",
                        "graph": {**descriptor, "parser_semantics_version": 7,
                                  "graph_fingerprint": "b" * 64},
                        "metrics": {**descriptor, "metrics_semantics_version": 4,
                                    "graph_fingerprint": "b" * 64},
                        "source_index": {**descriptor, "project_fingerprint": "c" * 64}}}


def _spec(**changes: object) -> TechnicalRunSpec:
    values = {"run_id": "run-1", "project_id": "project", "project_version": "1.2.3",
              "project_sha256": "d" * 64, "configuration_id": "baseline",
              "configuration_sha256": "e" * 64, "model": "offline-model",
              "prompt_version": "1.0.0", "prompt_sha256": "f" * 64,
              "context_variant": "overview", "toolset_variant": "full", "tool_budget": 3,
              "repeat": 1, "event": _event(), "authorized_tenant_id": "tenant-1"}
    values.update(changes)
    return TechnicalRunSpec(**values)  # type: ignore[arg-type]


def _envelope(**changes: object) -> TechnicalRunEnvelope:
    values = {
        "run_id": "run-1", "project_id": "project", "project_version": "1.2.3",
        "project_sha256": "d" * 64, "configuration_id": "baseline",
        "configuration_sha256": "e" * 64, "model": "offline-model",
        "prompt_version": "1.0.0", "prompt_sha256": "f" * 64,
        "context_variant": "overview", "toolset_variant": "full", "tool_budget": 3,
        "repeat": 1, "status": "passed", "delivery_decision": "ack",
        "checks": (TechnicalCheck("lifecycle", True),), "error": None,
        "llm_analysis": {"issues": [], "strengths": []}, "result_sha256": "a" * 64,
        "completed_event": {"event_type": "harness.completed.v1"}, "total_seconds": 0.1,
    }
    values.update(changes)
    return TechnicalRunEnvelope(**values)  # type: ignore[arg-type]


class Runner:
    def __init__(self, content: str = '{"issues":[],"strengths":[]}') -> None:
        self.content = content

    async def execute(self, request: object) -> HarnessResult:
        return HarnessResult(self.content)


class FailingRunner:
    async def execute(self, request: object) -> HarnessResult:
        raise RuntimeError("secret://token?payload=private")


class Materializer:
    @contextmanager
    def materialize(self, **kwargs: object):
        yield MaterializedInputs({"canonical.full": Path("graph")}, {"metrics.full": Path("metrics")},
                                 Path("index"), "b" * 64, "c" * 64)


class Clock:
    def now(self) -> datetime:
        return datetime(2026, 11, 25, tzinfo=timezone.utc)


class FailingPublisher:
    def __init__(self, publisher: object) -> None:
        self.publisher = publisher

    async def publish(self, event: object) -> None:
        raise RuntimeError("secret publish failure")


class MutatingPublisher:
    def __init__(self, publisher: object, field: str) -> None:
        self.publisher = publisher
        self.field = field

    async def publish(self, event: dict[str, object]) -> None:
        changed = dict(event)
        if self.field == "extra":
            changed["extra"] = "invalid"
        else:
            changed[self.field] = "wrong"
        await self.publisher.publish(changed)


class PublishingTwice:
    def __init__(self, publisher: object) -> None:
        self.publisher = publisher

    async def publish(self, event: object) -> None:
        await self.publisher.publish(event)
        await self.publisher.publish(event)


class SequenceMonotonic:
    def __init__(self, values: list[object]) -> None:
        self.values = iter(values)

    def __call__(self) -> float:
        value = next(self.values)
        if isinstance(value, Exception):
            raise value
        return value  # type: ignore[return-value]


def test_success_uses_real_handler_and_propagates_identity() -> None:
    envelope = asyncio.run(execute_technical_run(_spec(), runner=Runner(),
                                                 materializer=Materializer(), clock=Clock()))
    assert envelope.status == "passed"
    assert envelope.delivery_decision == "ack"
    assert envelope.result_sha256 == hashlib.sha256(b'{"issues":[],"strengths":[]}').hexdigest()
    assert envelope.completed_event["event_type"] == "harness.completed.v1"
    assert envelope.to_dict()["configuration_id"] == "baseline"
    assert all(check.passed for check in envelope.checks)
    schema = json.loads((Path(__file__).resolve().parents[1] / "schemas" / "technical_run.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(envelope.to_dict())


@pytest.mark.parametrize("change", [
    {"authorized_tenant_id": "other"},
    {"event": {**_event(), "event_type": "invalid"}},
])
def test_rejected_inputs_are_failed(change: dict[str, object]) -> None:
    result = asyncio.run(execute_technical_run(_spec(**change), runner=Runner(), materializer=Materializer()))
    assert result.status == "failed" and result.error.type == "delivery_rejected"
    assert result.llm_analysis is None


def test_runner_exception_is_sanitized_infrastructure_error() -> None:
    result = asyncio.run(execute_technical_run(_spec(), runner=FailingRunner(), materializer=Materializer()))
    assert result.status == "infrastructure_error"
    assert "secret" not in result.error.message and "private" not in result.error.message
    assert result.llm_analysis is None


def test_publisher_failure_after_save_is_observable_but_not_disclosed() -> None:
    result = asyncio.run(execute_technical_run(
        _spec(), runner=Runner(), materializer=Materializer(),
        publisher_factory=FailingPublisher,
    ))
    checks = {check.name: check.passed for check in result.checks}
    assert result.status == "infrastructure_error" and result.delivery_decision == "retry"
    assert checks["result_saved_once"] and checks["output_saved_before_publish"]
    assert not checks["publish_observed"] and not checks["publish_confirmed"]
    assert result.llm_analysis is None and result.result_sha256 is None
    assert result.completed_event is None and "secret" not in result.error.message


@pytest.mark.parametrize("field", ["extra", "tenant_id", "correlation_id", "causation_id"])
def test_ack_with_malformed_completed_event_is_failed(field: str) -> None:
    result = asyncio.run(execute_technical_run(
        _spec(), runner=Runner(), materializer=Materializer(),
        publisher_factory=lambda publisher: MutatingPublisher(publisher, field),
    ))
    assert result.status == "failed" and result.delivery_decision == "ack"
    assert not next(check.passed for check in result.checks
                    if check.name == "completed_event_contract_exact")
    assert result.completed_event is None and result.result_sha256 is None


@pytest.mark.parametrize(("field", "value"), [
    ("producer", {"service": "other", "version": "1"}),
    ("producer", {"service": "harness-service", "version": 1}),
    ("occurred_at", "2026-02-30T00:00:00Z"),
    ("occurred_at", "2026-11-25T25:00:00Z"),
])
def test_completed_event_rejects_wrong_producer_and_impossible_time(field: str, value: object) -> None:
    result = asyncio.run(execute_technical_run(
        _spec(), runner=Runner(), materializer=Materializer(),
        publisher_factory=lambda publisher: ReplacingPublisher(publisher, field, value),
    ))
    assert result.status == "failed"
    assert not next(check.passed for check in result.checks if check.name == "completed_event_contract_exact")


class ReplacingPublisher:
    def __init__(self, publisher: object, field: str, value: object) -> None:
        self.publisher = publisher; self.field = field; self.value = value

    async def publish(self, event: dict[str, object]) -> None:
        await self.publisher.publish({**event, self.field: self.value})


class ReplacingResultSchemaVersionPublisher:
    def __init__(self, publisher: object, value: object) -> None:
        self.publisher = publisher; self.value = value

    async def publish(self, event: dict[str, object]) -> None:
        payload = dict(event["payload"])
        payload["result"] = {**payload["result"], "schema_version": self.value}
        await self.publisher.publish({**event, "payload": payload})


@pytest.mark.parametrize("value", [True, 1.0])
def test_completed_event_rejects_non_integer_top_level_schema_version(value: object) -> None:
    result = asyncio.run(execute_technical_run(
        _spec(), runner=Runner(), materializer=Materializer(),
        publisher_factory=lambda publisher: ReplacingPublisher(publisher, "schema_version", value),
    ))
    checks = {check.name: check.passed for check in result.checks}
    assert result.status == "failed"
    assert not checks["completed_event_contract_exact"]


@pytest.mark.parametrize("value", [True, 1.0])
def test_completed_event_rejects_non_integer_result_schema_version(value: object) -> None:
    result = asyncio.run(execute_technical_run(
        _spec(), runner=Runner(), materializer=Materializer(),
        publisher_factory=lambda publisher: ReplacingResultSchemaVersionPublisher(publisher, value),
    ))
    checks = {check.name: check.passed for check in result.checks}
    assert result.status == "failed"
    assert not checks["completed_event_contract_exact"]
    assert not checks["result_descriptor_exact"]


def test_duplicate_publish_fails_exact_lifecycle_order() -> None:
    result = asyncio.run(execute_technical_run(
        _spec(), runner=Runner(), materializer=Materializer(), publisher_factory=PublishingTwice,
    ))
    assert result.status == "failed" and result.delivery_decision == "ack"
    assert not next(check.passed for check in result.checks if check.name == "lifecycle_order_exact")


@pytest.mark.parametrize("ending", [float("inf"), RuntimeError("clock failed")])
def test_invalid_elapsed_clock_value_has_safe_fallback(ending: object) -> None:
    result = asyncio.run(execute_technical_run(
        _spec(), runner=FailingRunner(), materializer=Materializer(),
        monotonic=SequenceMonotonic([1.0, ending]),
    ))
    assert result.status == "infrastructure_error" and result.total_seconds == 0.0


def test_ack_with_malformed_analysis_is_failed() -> None:
    result = asyncio.run(execute_technical_run(_spec(), runner=Runner("not-json"), materializer=Materializer()))
    assert result.status == "failed"
    assert result.delivery_decision == "ack"
    assert result.llm_analysis is None


def test_nested_inputs_and_serialized_outputs_are_immutable_and_fresh() -> None:
    event = _event()
    spec = _spec(event=event)
    event["producer"]["service"] = "mutated"
    assert spec.wire_event()["producer"]["service"] == "offline"
    with pytest.raises(TypeError):
        spec.event["producer"]["service"] = "mutated"
    result = asyncio.run(execute_technical_run(spec, runner=Runner(), materializer=Materializer()))
    first = result.to_dict(); first["llm_analysis"]["issues"].append({})
    assert result.to_dict()["llm_analysis"]["issues"] == []
    with pytest.raises(FrozenInstanceError):
        result.status = "failed"


def test_passed_envelope_requires_at_least_one_check() -> None:
    with pytest.raises(ValueError):
        _envelope(checks=())


@pytest.mark.parametrize(("field", "value", "error"), [
    ("llm_analysis", [], TypeError),
    ("completed_event", [], TypeError),
    ("llm_analysis", {"issues": "wrong", "strengths": []}, ValueError),
    ("total_seconds", True, ValueError),
    ("total_seconds", float("nan"), ValueError),
    ("run_id", "bad\x7fname", ValueError),
    ("schema_version", True, ValueError),
])
def test_envelope_runtime_rejects_schema_counterexamples(field: str, value: object, error: type[Exception]) -> None:
    with pytest.raises(error):
        _envelope(**{field: value})


@pytest.mark.parametrize(("status", "decision"), [
    ("failed", "retry"),
    ("infrastructure_error", "ack"),
    ("infrastructure_error", "reject"),
])
def test_envelope_rejects_status_delivery_contradictions(status: str, decision: str) -> None:
    with pytest.raises(ValueError):
        _envelope(
            status=status, delivery_decision=decision, checks=(),
            error=TechnicalError("failure", "Safe failure."), llm_analysis=None,
            result_sha256=None, completed_event=None,
        )
