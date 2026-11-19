from copy import deepcopy
from dataclasses import FrozenInstanceError

import pytest

from metrics_service.contracts import (
    EventEnvelope, Failure, GraphDescriptor, GraphReady, GraphReference,
    MetricsDescriptor, MetricsReady, Producer, decode_json, encode_json,
    from_mapping, to_mapping,
)


HASH = "b" * 64


def envelope(event_type, payload):
    return {"event_id": "event-2", "event_type": event_type, "schema_version": 1, "occurred_at": "2026-10-24T12:00:00Z", "correlation_id": "analysis-1", "causation_id": "event-1", "tenant_id": "tenant-1", "producer": {"service": "metrics-service", "version": "build-1"}, "payload": payload}


@pytest.mark.parametrize("event_type,payload", [
    ("graph.ready.v1", {"source_uri": "file:///source", "graph": {"uri": "file:///graph.json", "sha256": HASH, "size_bytes": 10, "schema_version": 1, "parser_semantics_version": 7, "graph_fingerprint": HASH}}),
    ("metrics.ready.v1", {"graph": {"uri": "file:///graph.json", "graph_fingerprint": HASH}, "metrics": {"uri": "file:///metrics.json", "sha256": HASH, "size_bytes": 20, "schema_version": 1, "metrics_semantics_version": 4}}),
    ("metrics.failed.v1", {"stage": "metrics", "failed_event_id": "event-1", "error_code": "invalid_graph", "message": "invalid graph", "retryable": False}),
])
def test_round_trip(event_type, payload):
    source = envelope(event_type, payload)
    event = from_mapping(source)
    assert to_mapping(event) == source
    assert decode_json(encode_json(event)) == event
    with pytest.raises(FrozenInstanceError):
        event.tenant_id = "other"


@pytest.mark.parametrize("event_type", ["metrics.ready.v2", "parser.start.v1", "unknown.v1"])
def test_unknown_event_is_rejected(event_type):
    with pytest.raises(ValueError):
        from_mapping(envelope(event_type, {}))


@pytest.mark.parametrize("field,bad", [("size_bytes", True), ("size_bytes", -1), ("sha256", "B" * 64), ("metrics_semantics_version", 3), ("schema_version", 2)])
def test_metrics_descriptor_is_strict(field, bad):
    metrics = {"uri": "file:///metrics.json", "sha256": HASH, "size_bytes": 20, "schema_version": 1, "metrics_semantics_version": 4}
    metrics[field] = bad
    with pytest.raises((TypeError, ValueError)):
        from_mapping(envelope("metrics.ready.v1", {"graph": {"uri": "file:///graph.json", "graph_fingerprint": HASH}, "metrics": metrics}))


def test_extra_payload_field_and_bool_retryable_are_rejected():
    payload = {"stage": "metrics", "failed_event_id": "event-1", "error_code": "failed", "message": "safe", "retryable": 0, "traceback": "secret"}
    with pytest.raises((TypeError, ValueError)):
        from_mapping(envelope("metrics.failed.v1", payload))


@pytest.mark.parametrize("timestamp", ["2026-10-24T12:00:00Z", "2026-10-24T12:00:00.1Z"])
def test_valid_utc_rfc3339_timestamps(timestamp):
    value = envelope("graph.ready.v1", {"source_uri": "file:///source", "graph": {"uri": "file:///graph.json", "sha256": HASH, "size_bytes": 0, "schema_version": 1, "parser_semantics_version": 7, "graph_fingerprint": HASH}})
    value["occurred_at"] = timestamp
    assert from_mapping(value).occurred_at == timestamp


@pytest.mark.parametrize("timestamp", ["2026-02-29T12:00:00Z", "2026-10-24T12:60:00Z", "2026-10-24T12:00:00+00:00", "2026-10-24T12:00:00z", None, True])
def test_invalid_utc_rfc3339_timestamps(timestamp):
    value = envelope("graph.ready.v1", {"source_uri": "file:///source", "graph": {"uri": "file:///graph.json", "sha256": HASH, "size_bytes": 0, "schema_version": 1, "parser_semantics_version": 7, "graph_fingerprint": HASH}})
    value["occurred_at"] = timestamp
    with pytest.raises((TypeError, ValueError)):
        from_mapping(value)


@pytest.mark.parametrize("wire", [b'{"event_id":"one","event_id":"two"}', b'\xff'])
def test_decode_rejects_duplicate_fields_and_invalid_utf8(wire):
    with pytest.raises(ValueError):
        decode_json(wire)


def test_decode_is_deeply_non_mutating_and_json_is_canonical():
    source = envelope("metrics.ready.v1", {"graph": {"uri": "file:///graph.json", "graph_fingerprint": HASH}, "metrics": {"uri": "file:///metrics.json", "sha256": HASH, "size_bytes": 0, "schema_version": 1, "metrics_semantics_version": 4}})
    original = deepcopy(source)
    encoded = encode_json(from_mapping(source))
    assert source == original
    assert encoded == encode_json(from_mapping(dict(reversed(list(source.items())))))
    assert encoded == encode_json(decode_json(encoded))


@pytest.mark.parametrize("event_type,payload", [
    ("metrics.failed.v1", {"stage": "parser", "failed_event_id": "event-1", "error_code": "failed", "message": "safe", "retryable": False}),
    ("metrics.failed.v1", {"stage": "metrics", "failed_event_id": "event-1", "error_code": "failed", "message": "safe", "retryable": 0}),
])
def test_failure_stage_and_boolean_are_exact(event_type, payload):
    with pytest.raises((TypeError, ValueError)):
        from_mapping(envelope(event_type, payload))


def test_graph_ready_rejects_bool_versions_and_embedded_canonical_dto():
    graph = {"uri": "file:///graph.json", "sha256": HASH, "size_bytes": 0, "schema_version": True, "parser_semantics_version": 7, "graph_fingerprint": HASH, "nodes": []}
    with pytest.raises((TypeError, ValueError)):
        from_mapping(envelope("graph.ready.v1", {"source_uri": "file:///source", "graph": graph}))


def test_direct_constructors_validate_metrics_payload_and_descriptor_families():
    with pytest.raises(ValueError):
        Producer("metrics-service", "\udfff")
    with pytest.raises(TypeError):
        GraphDescriptor("file:///graph", HASH, True, 1, 7, HASH)
    with pytest.raises(ValueError):
        GraphDescriptor("file:///graph", HASH, 1, 2, 7, HASH)
    with pytest.raises(TypeError):
        GraphReady("file:///source", {"uri": "file:///graph"})
    with pytest.raises(ValueError):
        GraphReference("file:///graph", "bad-hash")
    with pytest.raises(ValueError):
        MetricsDescriptor("file:///metrics", HASH, -1, 1, 4)
    with pytest.raises(TypeError):
        MetricsDescriptor("file:///metrics", HASH, 1, 1, True)
    with pytest.raises(TypeError):
        MetricsReady({"uri": "file:///graph"}, MetricsDescriptor("file:///metrics", HASH, 1, 1, 4))
    with pytest.raises(ValueError):
        Failure("parser", "event-1", "failed", "safe", False)
    with pytest.raises(TypeError):
        Failure("metrics", "event-1", "failed", "safe", 0)


def test_direct_metrics_envelope_validates_base_producer_and_payload_pair():
    payload = MetricsReady(
        GraphReference("file:///graph", HASH),
        MetricsDescriptor("file:///metrics", HASH, 1, 1, 4),
    )
    fields = dict(event_id="event-2", event_type="metrics.ready.v1", schema_version=1,
                  occurred_at="2026-10-24T12:00:00Z", correlation_id="analysis-1",
                  causation_id="event-1", tenant_id="tenant-1")
    with pytest.raises(TypeError):
        EventEnvelope(**fields, producer={"service": "metrics-service"}, payload=payload)
    with pytest.raises(ValueError):
        EventEnvelope(**{**fields, "event_id": ""},
                      producer=Producer("metrics-service", "build-1"), payload=payload)
    with pytest.raises(ValueError):
        EventEnvelope(**{**fields, "event_type": "graph.ready.v1"},
                      producer=Producer("metrics-service", "build-1"), payload=payload)


@pytest.mark.parametrize("wire", [
    b'{"value":NaN}', b'{"value":Infinity}', b'{"value":-Infinity}',
    '{"event_id":"\\ud800"}', '{"event_id":"\\ud83d\\ude00"}',
])
def test_decode_rejects_nonstandard_constants_and_all_surrogates(wire):
    with pytest.raises(ValueError):
        decode_json(wire)


def test_metrics_decode_rejects_nested_duplicate_field():
    wire = encode_json(from_mapping(envelope("metrics.ready.v1", {
        "graph": {"uri": "file:///graph.json", "graph_fingerprint": HASH},
        "metrics": {"uri": "file:///metrics.json", "sha256": HASH,
                    "size_bytes": 1, "schema_version": 1, "metrics_semantics_version": 4},
    })))
    wire = wire.replace(b'"graph_fingerprint"', b'"uri":"duplicate","graph_fingerprint"')
    with pytest.raises(ValueError, match="duplicate JSON field"):
        decode_json(wire)


def test_all_metrics_dtos_support_valid_direct_construction():
    producer = Producer("metrics-service", "build-😀")
    descriptor = GraphDescriptor("file:///graph-😀", HASH, 0, 1, 7, HASH)
    graph_ready = GraphReady("file:///source-😀", descriptor)
    graph = GraphReference("file:///graph-😀", HASH)
    metrics = MetricsDescriptor("file:///metrics-😀", HASH, 0, 1, 4)
    metrics_ready = MetricsReady(graph, metrics)
    failure = Failure("metrics", "event-1", "failed", "safe 😀", False)

    for event_type, payload in (
        ("graph.ready.v1", graph_ready),
        ("metrics.ready.v1", metrics_ready),
        ("metrics.failed.v1", failure),
    ):
        event = EventEnvelope(
            "event-😀", event_type, 1, "2026-10-24T12:00:00Z",
            "analysis-1", "cause-1", "tenant-1", producer, payload,
        )
        assert decode_json(encode_json(event)) == event


def test_from_mapping_builds_nested_dtos_without_recursion_and_preserves_non_bmp():
    source = envelope("metrics.ready.v1", {
        "graph": {"uri": "file:///graph-😀", "graph_fingerprint": HASH},
        "metrics": {"uri": "file:///metrics-😀", "sha256": HASH,
                    "size_bytes": 0, "schema_version": 1,
                    "metrics_semantics_version": 4},
    })
    source["event_id"] = "event-😀"
    event = from_mapping(source)
    assert type(event.payload) is MetricsReady
    assert type(event.payload.graph) is GraphReference
    assert type(event.payload.metrics) is MetricsDescriptor
    assert decode_json(encode_json(event)).event_id == "event-😀"
