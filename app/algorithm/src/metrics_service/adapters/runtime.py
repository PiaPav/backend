"""In-memory transport test adapters and system primitives."""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from typing import Mapping

from ..application.models import DeliveryContext, DeliveryDecision
from ..application.ports import DeliveryHandler
from ..contracts import EventEnvelope


class ManualInputSignalSource:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._handler: DeliveryHandler | None = None
        self._decisions: list[DeliveryDecision] = []

    def start(self, handler: DeliveryHandler) -> None:
        with self._lock:
            if self._handler is not None:
                raise RuntimeError("source is already started")
            self._handler = handler

    def stop(self) -> None:
        with self._lock:
            self._handler = None

    def deliver(self, wire: Mapping[str, object], context: DeliveryContext) -> DeliveryDecision:
        with self._lock:
            handler = self._handler
        if handler is None:
            raise RuntimeError("source is not started")
        decision = handler(wire, context)
        with self._lock:
            self._decisions.append(decision)
        return decision

    @property
    def decisions(self) -> tuple[DeliveryDecision, ...]:
        with self._lock:
            return tuple(self._decisions)


class RecordingEventPublisher:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: list[EventEnvelope] = []
        self._failure: BaseException | None = None

    def fail_with(self, error: BaseException | None) -> None:
        with self._lock:
            self._failure = error

    def publish(self, event: EventEnvelope) -> None:
        with self._lock:
            if self._failure is not None:
                raise self._failure
            self._events.append(event)

    @property
    def events(self) -> tuple[EventEnvelope, ...]:
        with self._lock:
            return tuple(self._events)


class UtcClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class UUIDEventIdGenerator:
    def new_event_id(self) -> str:
        return str(uuid.uuid4())


__all__ = ["ManualInputSignalSource", "RecordingEventPublisher", "UUIDEventIdGenerator", "UtcClock"]
