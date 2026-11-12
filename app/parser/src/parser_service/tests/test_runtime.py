import threading

import pytest

from parser_service.adapters.runtime import ManualInputSignalSource
from parser_service.application.models import DeliveryContext, DeliveryDecision
from parser_service.runtime import ObservationKind, RuntimeState, ServiceRuntime


def test_lifecycle_and_exact_decision_settlement() -> None:
    source = ManualInputSignalSource()
    runtime = ServiceRuntime(source=source, handler=lambda wire, context: DeliveryDecision.REJECT)
    runtime.start()
    assert runtime.state is RuntimeState.RUNNING
    assert source.deliver({}, DeliveryContext("tenant")) is DeliveryDecision.REJECT
    assert source.decisions == (DeliveryDecision.REJECT,)
    assert runtime.stop(0) is True
    assert runtime.state is RuntimeState.STOPPED
    with pytest.raises(RuntimeError):
        runtime.start()


def test_handler_and_observer_failures_are_isolated() -> None:
    class BadObserver:
        def observe(self, observation) -> None:
            raise RuntimeError("private exception text")

    source = ManualInputSignalSource()
    runtime = ServiceRuntime(source=source, handler=lambda wire, context: 1 / 0,
                             observer=BadObserver())
    runtime.start()
    assert source.deliver({}, DeliveryContext("tenant")) is DeliveryDecision.RETRY
    assert runtime.stop() is True


def test_stop_timeout_observes_only_safe_runtime_metadata() -> None:
    entered, release = threading.Event(), threading.Event()
    observations = []
    source = ManualInputSignalSource()

    def handler(wire, context):
        entered.set(); release.wait(); return DeliveryDecision.ACK

    class Observer:
        def observe(self, observation) -> None:
            observations.append(observation)

    runtime = ServiceRuntime(source=source, handler=handler, observer=Observer())
    runtime.start()
    worker = threading.Thread(target=source.deliver,
                              args=({"payload": "secret"}, DeliveryContext("private-tenant")))
    worker.start(); assert entered.wait(1)
    assert runtime.stop(0) is False
    assert observations[-2].kind is ObservationKind.DRAIN_TIMEOUT
    assert set(vars(observations[-2])) == {"kind", "state", "decision", "active_deliveries"}
    release.set(); worker.join(1)


@pytest.mark.parametrize("decision", list(DeliveryDecision))
def test_source_settles_each_handler_decision_once_without_runtime_retry(decision) -> None:
    calls = []
    source = ManualInputSignalSource()
    runtime = ServiceRuntime(
        source=source,
        handler=lambda wire, context: calls.append((wire, context)) or decision,
    )
    runtime.start()
    assert source.deliver({}, DeliveryContext("tenant")) is decision
    assert len(calls) == 1
    assert source.decisions == (decision,)
    runtime.stop()


def test_start_failure_is_terminal_and_invalid_decision_becomes_retry() -> None:
    class FailingSource:
        def start(self, handler) -> None:
            raise OSError("unavailable")

        def stop(self) -> None:
            raise AssertionError("must not stop after failed startup")

    failed = ServiceRuntime(source=FailingSource(), handler=lambda wire, context: DeliveryDecision.ACK)
    with pytest.raises(OSError, match="unavailable"):
        failed.start()
    assert failed.state is RuntimeState.STOPPED
    with pytest.raises(RuntimeError, match="single-use"):
        failed.start()

    source = ManualInputSignalSource()
    runtime = ServiceRuntime(source=source, handler=lambda wire, context: "ack")
    runtime.start()
    assert source.deliver({}, DeliveryContext("tenant")) is DeliveryDecision.RETRY
    assert source.decisions == (DeliveryDecision.RETRY,)
    runtime.stop()


def test_delivery_arriving_while_stopping_is_retried_without_calling_handler() -> None:
    stopping = threading.Event()

    class RetainingSource:
        handler = None

        def start(self, handler) -> None:
            self.handler = handler

        def stop(self) -> None:
            stopping.set()

    calls = []
    source = RetainingSource()
    runtime = ServiceRuntime(source=source, handler=lambda wire, context: calls.append(1))
    runtime.start()
    worker = threading.Thread(target=runtime.stop)
    worker.start(); assert stopping.wait(1)
    assert source.handler({}, DeliveryContext("tenant")) is DeliveryDecision.RETRY
    worker.join(1)
    assert calls == []


def test_completion_observer_can_stop_runtime_after_delivery_accounting() -> None:
    source = ManualInputSignalSource()
    observations = []
    runtime = None

    class Observer:
        def observe(self, observation) -> None:
            observations.append(observation)
            if observation.kind is ObservationKind.COMPLETION:
                assert runtime.stop() is True

    runtime = ServiceRuntime(
        source=source,
        handler=lambda wire, context: DeliveryDecision.ACK,
        observer=Observer(),
    )
    runtime.start()
    worker = threading.Thread(
        target=source.deliver,
        args=({}, DeliveryContext("tenant")),
    )
    worker.start(); worker.join(1)

    assert not worker.is_alive()
    assert runtime.active_deliveries == 0
    assert runtime.state is RuntimeState.STOPPED
    completions = [item for item in observations if item.kind is ObservationKind.COMPLETION]
    assert len(completions) == 1
    assert completions[0].decision is DeliveryDecision.ACK
    assert completions[0].active_deliveries == 0
    assert source.decisions == (DeliveryDecision.ACK,)


@pytest.mark.parametrize("drain_timeout", [float("nan"), float("inf"), float("-inf"), -1, True, "1"])
def test_stop_rejects_invalid_drain_timeout_without_changing_state(drain_timeout) -> None:
    source = ManualInputSignalSource()
    runtime = ServiceRuntime(source=source, handler=lambda wire, context: DeliveryDecision.ACK)
    runtime.start()

    with pytest.raises(ValueError, match="finite nonnegative real number"):
        runtime.stop(drain_timeout)

    assert runtime.state is RuntimeState.RUNNING
    assert runtime.stop(0) is True
