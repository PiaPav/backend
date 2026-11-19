"""Transport-neutral, single-use Parser Service runtime."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from enum import Enum
from math import isfinite
from numbers import Real
from typing import Mapping, Protocol

from .application.models import DeliveryContext, DeliveryDecision
from .application.ports import DeliveryHandler, InputSignalSource


class RuntimeState(str, Enum):
    CREATED = "created"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"


class ObservationKind(str, Enum):
    LIFECYCLE = "lifecycle"
    COMPLETION = "completion"
    DRAIN_TIMEOUT = "drain_timeout"


@dataclass(frozen=True)
class RuntimeObservation:
    """Privacy-safe runtime metadata; it deliberately has no delivery fields."""
    kind: ObservationKind
    state: RuntimeState
    decision: DeliveryDecision | None = None
    active_deliveries: int = 0


class RuntimeObserver(Protocol):
    def observe(self, observation: RuntimeObservation) -> None: ...


class ServiceRuntime:
    def __init__(self, *, source: InputSignalSource, handler: DeliveryHandler,
                 observer: RuntimeObserver | None = None) -> None:
        self._source, self._handler, self._observer = source, handler, observer
        self._condition = threading.Condition()
        self._state, self._active = RuntimeState.CREATED, 0

    @property
    def state(self) -> RuntimeState:
        with self._condition:
            return self._state

    @property
    def active_deliveries(self) -> int:
        with self._condition:
            return self._active

    def start(self) -> None:
        with self._condition:
            if self._state is not RuntimeState.CREATED:
                raise RuntimeError("runtime is single-use")
            self._state = RuntimeState.STARTING
        self._notify(ObservationKind.LIFECYCLE)
        try:
            self._source.start(self._deliver)
        except BaseException:
            with self._condition:
                self._state = RuntimeState.STOPPED
            self._notify(ObservationKind.LIFECYCLE)
            raise
        with self._condition:
            if self._state is not RuntimeState.STARTING:
                raise RuntimeError("runtime state changed while starting")
            self._state = RuntimeState.RUNNING
        self._notify(ObservationKind.LIFECYCLE)

    def stop(self, drain_timeout: float | None = None) -> bool:
        if (drain_timeout is not None
                and (isinstance(drain_timeout, bool)
                     or not isinstance(drain_timeout, Real)
                     or not isfinite(drain_timeout)
                     or drain_timeout < 0)):
            raise ValueError("drain_timeout must be a finite nonnegative real number or None")
        with self._condition:
            if self._state is not RuntimeState.RUNNING:
                raise RuntimeError("runtime is not running")
            self._state = RuntimeState.STOPPING
        self._notify(ObservationKind.LIFECYCLE)
        try:
            self._source.stop()
        finally:
            deadline = None if drain_timeout is None else time.monotonic() + drain_timeout
            with self._condition:
                while self._active:
                    remaining = None if deadline is None else deadline - time.monotonic()
                    if remaining is not None and remaining <= 0:
                        break
                    self._condition.wait(remaining)
                drained = self._active == 0
                active = self._active
                self._state = RuntimeState.STOPPED
            if not drained:
                self._notify(ObservationKind.DRAIN_TIMEOUT, active=active)
            self._notify(ObservationKind.LIFECYCLE)
        return drained

    def _deliver(self, wire: Mapping[str, object], context: DeliveryContext) -> DeliveryDecision:
        with self._condition:
            if self._state not in {RuntimeState.STARTING, RuntimeState.RUNNING}:
                return DeliveryDecision.RETRY
            self._active += 1
        try:
            decision = self._handler(wire, context)
            if type(decision) is not DeliveryDecision:
                decision = DeliveryDecision.RETRY
        except BaseException:
            decision = DeliveryDecision.RETRY
        finally:
            with self._condition:
                self._active -= 1
                self._condition.notify_all()
        self._notify(ObservationKind.COMPLETION, decision=decision)
        return decision

    def _notify(self, kind: ObservationKind, *, decision: DeliveryDecision | None = None,
                active: int | None = None) -> None:
        if self._observer is None:
            return
        with self._condition:
            observation = RuntimeObservation(kind, self._state, decision,
                                             self._active if active is None else active)
        try:
            self._observer.observe(observation)
        except BaseException:
            pass


__all__ = ["ObservationKind", "RuntimeObservation", "RuntimeObserver", "RuntimeState", "ServiceRuntime"]
