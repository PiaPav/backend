"""Observable offline execution of the public harness handler contract."""

from __future__ import annotations

import hashlib
import math
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Callable, Mapping, Protocol

from harness_service.harness_handler import (
    ArtifactDescriptor, Claim, ClaimDisposition, DeliveryContext, DeliveryDecision,
    HarnessHandler,
    EventPublisher,
)
from response_models.models import LLMAnalysis

_SHA = re.compile(r"[0-9a-f]{64}")
_SEMVER = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?")
_UTC_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z")


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise TypeError("mapping keys must be strings")
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if type(value) is float and not math.isfinite(value):
        raise ValueError("JSON numbers must be finite")
    if value is None or type(value) in (str, int, float, bool):
        return value
    raise TypeError("value must be JSON-compatible")


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _safe(value: object, name: str) -> None:
    if type(value) is not str or not value or any(ord(c) < 32 or ord(c) == 127 or c in "/\\" for c in value):
        raise ValueError(f"{name} must be a non-empty safe string")


@dataclass(frozen=True, slots=True)
class TechnicalCheck:
    name: str
    passed: bool
    details: str | None = None

    def __post_init__(self) -> None:
        _safe(self.name, "check.name")
        if type(self.passed) is not bool or (self.details is not None and type(self.details) is not str):
            raise TypeError("invalid technical check")

    def to_dict(self) -> dict[str, object]:
        return {"name": self.name, "passed": self.passed, "details": self.details}


@dataclass(frozen=True, slots=True)
class TechnicalError:
    type: str
    message: str

    def __post_init__(self) -> None:
        _safe(self.type, "error.type")
        _safe(self.message, "error.message")

    def to_dict(self) -> dict[str, str]:
        return {"type": self.type, "message": self.message}


@dataclass(frozen=True, slots=True)
class TechnicalRunSpec:
    run_id: str
    project_id: str
    project_version: str
    project_sha256: str
    configuration_id: str
    configuration_sha256: str
    model: str
    prompt_version: str
    prompt_sha256: str
    context_variant: str
    toolset_variant: str
    tool_budget: int
    repeat: int
    event: Mapping[str, object]
    authorized_tenant_id: str

    def __post_init__(self) -> None:
        for name in ("run_id", "project_id", "configuration_id", "model", "context_variant", "toolset_variant", "authorized_tenant_id"):
            _safe(getattr(self, name), name)
        if _SEMVER.fullmatch(self.project_version) is None or _SEMVER.fullmatch(self.prompt_version) is None:
            raise ValueError("versions must be SemVer")
        for name in ("project_sha256", "configuration_sha256", "prompt_sha256"):
            if _SHA.fullmatch(getattr(self, name)) is None:
                raise ValueError(f"{name} must be a lowercase SHA-256")
        if type(self.tool_budget) is not int or self.tool_budget < 1 or type(self.repeat) is not int or self.repeat < 1:
            raise ValueError("tool_budget and repeat must be positive integers")
        object.__setattr__(self, "event", _freeze(self.event))

    def wire_event(self) -> dict[str, object]:
        value = _thaw(self.event)
        assert isinstance(value, dict)
        return value


@dataclass(frozen=True, slots=True)
class TechnicalRunEnvelope:
    run_id: str; project_id: str; project_version: str; project_sha256: str
    configuration_id: str; configuration_sha256: str; model: str
    prompt_version: str; prompt_sha256: str; context_variant: str; toolset_variant: str
    tool_budget: int; repeat: int; status: str; delivery_decision: str | None
    checks: tuple[TechnicalCheck, ...]; error: TechnicalError | None
    llm_analysis: Mapping[str, object] | None; result_sha256: str | None
    completed_event: Mapping[str, object] | None; total_seconds: float
    schema_version: int = 1

    def __post_init__(self) -> None:
        for name in ("run_id", "project_id", "configuration_id", "model", "context_variant", "toolset_variant"):
            _safe(getattr(self, name), name)
        if _SEMVER.fullmatch(self.project_version) is None or _SEMVER.fullmatch(self.prompt_version) is None:
            raise ValueError("versions must be SemVer")
        for name in ("project_sha256", "configuration_sha256", "prompt_sha256"):
            if _SHA.fullmatch(getattr(self, name)) is None:
                raise ValueError(f"{name} must be a lowercase SHA-256")
        if type(self.tool_budget) is not int or self.tool_budget < 1 or type(self.repeat) is not int or self.repeat < 1:
            raise ValueError("tool_budget and repeat must be positive integers")
        if self.delivery_decision not in {None, "ack", "reject", "retry"}:
            raise ValueError("invalid delivery decision")
        if any(not isinstance(check, TechnicalCheck) for check in self.checks):
            raise TypeError("checks must contain TechnicalCheck values")
        if self.error is not None and not isinstance(self.error, TechnicalError):
            raise TypeError("error must be a TechnicalError")
        if self.result_sha256 is not None and _SHA.fullmatch(self.result_sha256) is None:
            raise ValueError("result_sha256 must be a lowercase SHA-256")
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("schema_version must be integer 1")
        if self.status not in {"passed", "failed", "infrastructure_error"}:
            raise ValueError("invalid technical envelope status")
        if type(self.total_seconds) not in (int, float) or not math.isfinite(self.total_seconds) or self.total_seconds < 0:
            raise ValueError("total_seconds must be finite and nonnegative")
        object.__setattr__(self, "checks", tuple(self.checks))
        if self.llm_analysis is not None:
            if not isinstance(self.llm_analysis, Mapping):
                raise TypeError("llm_analysis must be a mapping")
            normalized = self.llm_analysis
            if self.status == "passed":
                normalized = LLMAnalysis.model_validate(dict(self.llm_analysis)).model_dump(mode="json")
            object.__setattr__(self, "llm_analysis", _freeze(normalized))
        if self.completed_event is not None:
            if not isinstance(self.completed_event, Mapping):
                raise TypeError("completed_event must be a mapping")
            object.__setattr__(self, "completed_event", _freeze(self.completed_event))
        passed = self.status == "passed"
        allowed_decisions = {
            "passed": {"ack"}, "failed": {"ack", "reject"},
            "infrastructure_error": {"retry", None},
        }
        if self.delivery_decision not in allowed_decisions[self.status]:
            raise ValueError("status and delivery decision are contradictory")
        if passed != (self.delivery_decision == "ack" and bool(self.checks) and self.error is None and self.llm_analysis is not None and self.result_sha256 is not None and self.completed_event is not None and all(c.passed for c in self.checks)):
            raise ValueError("technical envelope invariants are contradictory")
        if not passed and (self.error is None or self.llm_analysis is not None or self.result_sha256 is not None or self.completed_event is not None):
            raise ValueError("non-passed envelope must contain only a safe error")

    def to_dict(self) -> dict[str, object]:
        return {"schema_version": self.schema_version, "run_id": self.run_id, "project_id": self.project_id,
                "project_version": self.project_version, "project_sha256": self.project_sha256,
                "configuration_id": self.configuration_id, "configuration_sha256": self.configuration_sha256,
                "model": self.model, "prompt_version": self.prompt_version, "prompt_sha256": self.prompt_sha256,
                "context_variant": self.context_variant, "toolset_variant": self.toolset_variant,
                "tool_budget": self.tool_budget, "repeat": self.repeat, "status": self.status,
                "delivery_decision": self.delivery_decision, "checks": [c.to_dict() for c in self.checks],
                "error": None if self.error is None else self.error.to_dict(),
                "llm_analysis": _thaw(self.llm_analysis), "result_sha256": self.result_sha256,
                "completed_event": _thaw(self.completed_event), "total_seconds": self.total_seconds}


class _ResultStore:
    def __init__(self, journal: list[str]) -> None: self.saved: list[tuple[str, ArtifactDescriptor]] = []; self._journal = journal
    async def save(self, *, tenant_id: str, event_id: str, content: str) -> ArtifactDescriptor:
        raw = content.encode("utf-8")
        descriptor = ArtifactDescriptor(f"benchmark-memory://{event_id}", hashlib.sha256(raw).hexdigest(), len(raw), 1)
        self.saved.append((content, descriptor)); self._journal.append("result_save"); return descriptor


class _Idempotency:
    def __init__(self, journal: list[str]) -> None: self.output = None; self.published = False; self._journal = journal
    async def claim(self, *, key: str, payload_digest: str) -> Claim:
        self._journal.append("claim"); return Claim(ClaimDisposition.NEW, "benchmark-claim")
    async def save_output(self, *, key: str, claim_token: str, output_event: Mapping[str, object]) -> None:
        self.output = _freeze(output_event); self._journal.append("save_output")
    async def mark_published(self, *, key: str, claim_token: str) -> None:
        if self.output is None: raise RuntimeError("output was not saved")
        self.published = True; self._journal.append("mark_published")


class _Publisher:
    def __init__(self, idempotency: _Idempotency, journal: list[str]) -> None: self.events = []; self._idempotency = idempotency; self._journal = journal
    async def publish(self, event: Mapping[str, object]) -> None:
        if self._idempotency.output is None: raise RuntimeError("publish preceded save_output")
        self.events.append(_freeze(event)); self._journal.append("publish")


class TechnicalPublisherFactory(Protocol):
    """Benchmark extension point for instrumenting the final publish boundary."""

    def __call__(self, publisher: EventPublisher) -> EventPublisher: ...


def _error(kind: str, message: str) -> TechnicalError: return TechnicalError(kind, message)


async def execute_technical_run(spec: TechnicalRunSpec, *, runner: object, materializer: object,
                                clock: object | None = None,
                                publisher_factory: TechnicalPublisherFactory | None = None,
                                monotonic: Callable[[], float] = time.perf_counter) -> TechnicalRunEnvelope:
    started = _clock_value(monotonic); journal: list[str] = []
    store = _ResultStore(journal); idem = _Idempotency(journal); observed_publisher = _Publisher(idem, journal)
    decision: DeliveryDecision | None = None
    try:
        publisher: EventPublisher = (publisher_factory(observed_publisher)
                                     if publisher_factory is not None else observed_publisher)
        handler = HarnessHandler(runner=runner, materializer=materializer, result_store=store,
                                 idempotency=idem, publisher=publisher, clock=clock)
        decision = await handler.handle(spec.wire_event(), DeliveryContext(spec.authorized_tenant_id))
        if decision is DeliveryDecision.RETRY:
            checks = _retry_checks(store, idem, observed_publisher, journal)
            return _envelope(spec, "infrastructure_error", "retry", checks, _error("delivery_retry", "Harness requested a safe retry."), _elapsed(monotonic, started))
        if decision is DeliveryDecision.REJECT:
            return _envelope(spec, "failed", "reject", (TechnicalCheck("input_accepted", False),), _error("delivery_rejected", "Harness rejected the input."), _elapsed(monotonic, started))
        checks, analysis, digest, event = _observe(spec, store, idem, observed_publisher, journal)
        if not all(item.passed for item in checks):
            return _envelope(spec, "failed", "ack", checks, _error("technical_contract_failed", "Technical lifecycle validation failed."), _elapsed(monotonic, started))
        return _envelope(spec, "passed", "ack", checks, None, _elapsed(monotonic, started), analysis, digest, event)
    except Exception:
        return _envelope(spec, "infrastructure_error", None, (TechnicalCheck("execution_boundary_completed", False),),
                          _error("execution_boundary_error", "Technical execution failed at the boundary."), _elapsed(monotonic, started))


def _clock_value(monotonic: Callable[[], float]) -> float | None:
    try:
        value = monotonic()
        return float(value) if type(value) in (int, float) and math.isfinite(value) else None
    except Exception:
        return None


def _elapsed(monotonic: Callable[[], float], started: float | None) -> float:
    finished = _clock_value(monotonic)
    if started is None or finished is None:
        return 0.0
    elapsed = finished - started
    return elapsed if math.isfinite(elapsed) and elapsed >= 0 else 0.0


def _retry_checks(store: _ResultStore, idem: _Idempotency,
                   publisher: _Publisher, journal: list[str]) -> tuple[TechnicalCheck, ...]:
    expected = ["claim", "result_save", "save_output", "publish", "mark_published"]
    return (
        TechnicalCheck("result_saved_once", len(store.saved) == 1),
        TechnicalCheck("output_saved_before_publish", idem.output is not None),
        TechnicalCheck("publish_observed", len(publisher.events) == 1),
        TechnicalCheck("publish_confirmed", idem.published),
        TechnicalCheck("lifecycle_order_exact", journal == expected[:len(journal)]),
    )


def _observe(spec: TechnicalRunSpec, store: _ResultStore, idem: _Idempotency,
              publisher: _Publisher, journal: list[str]) -> tuple[tuple[TechnicalCheck, ...], dict[str, object] | None, str | None, Mapping[str, object] | None]:
    single = len(store.saved) == 1
    content, descriptor = store.saved[0] if len(store.saved) == 1 else (None, None)
    event = publisher.events[0] if len(publisher.events) == 1 else None
    result = event.get("payload", {}).get("result", {}) if isinstance(event, Mapping) and isinstance(event.get("payload"), Mapping) else {}
    match = (descriptor is not None and isinstance(result, Mapping)
             and set(result) == {"uri", "sha256", "size_bytes", "schema_version"}
             and type(result.get("uri")) is str and result["uri"] == descriptor.uri
             and type(result.get("sha256")) is str and result["sha256"] == descriptor.sha256
             and type(result.get("size_bytes")) is int and result["size_bytes"] == descriptor.size_bytes
             and type(result.get("schema_version")) is int
             and result["schema_version"] == descriptor.schema_version)
    source = spec.event
    top_keys = {"event_id", "event_type", "schema_version", "occurred_at", "correlation_id", "causation_id", "tenant_id", "producer", "payload"}
    completed = (isinstance(event, Mapping) and set(event) == top_keys
                 and event.get("event_type") == "harness.completed.v1"
                 and type(event.get("schema_version")) is int and event["schema_version"] == 1
                  and type(event.get("occurred_at")) is str
                  and _valid_utc_timestamp(event["occurred_at"])
                 and event.get("event_id") == f"{source.get('event_id')}:harness-result"
                 and event.get("tenant_id") == source.get("tenant_id")
                 and event.get("correlation_id") == source.get("correlation_id")
                 and event.get("causation_id") == source.get("event_id")
                  and isinstance(event.get("producer"), Mapping)
                  and set(event["producer"]) == {"service", "version"}
                  and event["producer"] == {"service": "harness-service", "version": "1"}
                 and isinstance(event.get("payload"), Mapping)
                 and set(event["payload"]) == {"result"}
                 and isinstance(result, Mapping) and set(result) == {"uri", "sha256", "size_bytes", "schema_version"}
                 and type(result.get("schema_version")) is int and result["schema_version"] == 1)
    analysis = None
    valid = False
    if content is not None:
        try:
            analysis = LLMAnalysis.model_validate_json(content).model_dump(mode="json")
            valid = True
        except Exception:
            pass
    content_descriptor = (content is not None and descriptor is not None
                          and descriptor.sha256 == hashlib.sha256(content.encode("utf-8")).hexdigest()
                          and descriptor.size_bytes == len(content.encode("utf-8"))
                          and descriptor.schema_version == 1)
    lifecycle = (idem.output == event and len(publisher.events) == 1
                  and publisher.events[0] == event and idem.published
                  and journal == ["claim", "result_save", "save_output", "publish", "mark_published"])
    checks = (TechnicalCheck("result_saved_once", single),
               TechnicalCheck("output_saved_published_and_confirmed", lifecycle),
               TechnicalCheck("lifecycle_order_exact", journal == ["claim", "result_save", "save_output", "publish", "mark_published"]),
              TechnicalCheck("completed_event_contract_exact", completed),
              TechnicalCheck("result_descriptor_exact", match),
              TechnicalCheck("result_content_descriptor_valid", content_descriptor),
              TechnicalCheck("llm_analysis_valid", valid))
    return checks, analysis, descriptor.sha256 if descriptor else None, event


def _valid_utc_timestamp(value: str) -> bool:
    if _UTC_TIMESTAMP.fullmatch(value) is None:
        return False
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
        return parsed.tzinfo is not None and parsed.utcoffset() == timezone.utc.utcoffset(parsed)
    except ValueError:
        return False


def _envelope(spec: TechnicalRunSpec, status: str, decision: str | None, checks: tuple[TechnicalCheck, ...],
              error: TechnicalError | None, elapsed: float, analysis: Mapping[str, object] | None = None,
              digest: str | None = None, event: Mapping[str, object] | None = None) -> TechnicalRunEnvelope:
    return TechnicalRunEnvelope(spec.run_id, spec.project_id, spec.project_version, spec.project_sha256,
        spec.configuration_id, spec.configuration_sha256, spec.model, spec.prompt_version, spec.prompt_sha256,
        spec.context_variant, spec.toolset_variant, spec.tool_budget, spec.repeat, status, decision, checks,
        error, analysis, digest, event, max(0.0, elapsed))


__all__ = ["TechnicalCheck", "TechnicalError", "TechnicalPublisherFactory", "TechnicalRunEnvelope", "TechnicalRunSpec", "execute_technical_run"]
