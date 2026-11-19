from copy import deepcopy
from dataclasses import FrozenInstanceError

import pytest

from parser_service.contracts import (
    EventEnvelope, Failure, GraphDescriptor, GraphReady, ParserStart, Producer,
    RequestedGraph, decode_json, encode_json, from_mapping, to_mapping,
)


HASH = "a" * 64


def envelope(event_type: str, payload: dict[str, object]) -> dict[str, object]:
    return {
        "event_id": "event-1", "event_type": event_type, "schema_version": 1,
        "occurred_at": "2026-10-24T12:00:00.123Z", "correlation_id": "analysis-1",
        "causation_id": "cause-1", "tenant_id": "tenant-1",
        "producer": {"service": "parser-service", "version": "build-1"},
        "payload": payload,
    }


@pytest.mark.parametrize("event_type,payload", [
    ("parser.start.v1", {"source_uri": "file:///source", "requested_graph": {"schema_version": 1, "parser_semantics_version": 7}}),
    ("graph.ready.v1", {"source_uri": "file:///source", "graph": {"uri": "file:///graph.json", "sha256": HASH, "size_bytes": 12, "schema_version": 1, "parser_semantics_version": 7, "graph_fingerprint": HASH}}),
    ("parser.failed.v1", {"stage": "parser", "failed_event_id": "event-1", "error_code": "source_not_found", "message": "not found", "retryable": False}),
])
def test_round_trip_is_canonical(event_type, payload):
    source = envelope(event_type, payload)
    event = from_mapping(source)
    assert to_mapping(event) == source
    assert decode_json(encode_json(event)) == event
    assert b": " not in encode_json(event)
    assert b", " not in encode_json(event)
    assert encode_json(event) == encode_json(event)


def test_decode_does_not_mutate_input_and_models_are_frozen():
    source = envelope("parser.start.v1", {"source_uri": "file:///source", "requested_graph": {"schema_version": 1, "parser_semantics_version": 7}})
    original = repr(source)
    event = from_mapping(source)
    assert repr(source) == original
    with pytest.raises(FrozenInstanceError):
        event.event_id = "changed"


@pytest.mark.parametrize("change", [
    lambda value: value.update(extra=True),
    lambda value: value.pop("tenant_id"),
    lambda value: value.update(schema_version=True),
    lambda value: value.update(schema_version=2),
    lambda value: value.update(occurred_at="2026-10-24T12:00:00+00:00"),
    lambda value: value.update(event_type="parser.start.v2"),
])
def test_rejects_invalid_envelope(change):
    value = envelope("parser.start.v1", {"source_uri": "file:///source", "requested_graph": {"schema_version": 1, "parser_semantics_version": 7}})
    change(value)
    with pytest.raises((TypeError, ValueError)):
        from_mapping(value)


@pytest.mark.parametrize("field,bad", [("size_bytes", True), ("size_bytes", -1), ("sha256", "A" * 64), ("graph_fingerprint", "abc"), ("parser_semantics_version", 6)])
def test_graph_descriptor_is_strict(field, bad):
    graph = {"uri": "file:///graph.json", "sha256": HASH, "size_bytes": 12, "schema_version": 1, "parser_semantics_version": 7, "graph_fingerprint": HASH}
    graph[field] = bad
    with pytest.raises((TypeError, ValueError)):
        from_mapping(envelope("graph.ready.v1", {"source_uri": "file:///source", "graph": graph}))


def test_failure_rejects_unsafe_message_and_wrong_stage():
    for stage, message in (("metrics", "safe"), ("parser", "trace\nsecret")):
        with pytest.raises(ValueError):
            from_mapping(envelope("parser.failed.v1", {"stage": stage, "failed_event_id": "event-1", "error_code": "failed", "message": message, "retryable": False}))


@pytest.mark.parametrize("timestamp", [
    "2026-10-24T12:00:00Z", "2026-10-24T12:00:00.123456Z",
])
def test_valid_utc_rfc3339_timestamps(timestamp):
    value = envelope("parser.start.v1", {"source_uri": "file:///source", "requested_graph": {"schema_version": 1, "parser_semantics_version": 7}})
    value["occurred_at"] = timestamp
    assert from_mapping(value).occurred_at == timestamp


@pytest.mark.parametrize("timestamp", [
    "2026-02-29T12:00:00Z", "2026-10-24T24:00:00Z", "2026-10-24 12:00:00Z",
    "2026-10-24T12:00:00+00:00", "2026-10-24T12:00:00z", 1, True,
])
def test_invalid_utc_rfc3339_timestamps(timestamp):
    value = envelope("parser.start.v1", {"source_uri": "file:///source", "requested_graph": {"schema_version": 1, "parser_semantics_version": 7}})
    value["occurred_at"] = timestamp
    with pytest.raises((TypeError, ValueError)):
        from_mapping(value)


@pytest.mark.parametrize("wire", [
    b'{"event_id":"one","event_id":"two"}',
    b'\xff',
])
def test_decode_rejects_duplicate_fields_and_invalid_utf8(wire):
    with pytest.raises(ValueError):
        decode_json(wire)


def test_nested_duplicate_json_field_is_rejected():
    wire = encode_json(from_mapping(envelope("parser.start.v1", {"source_uri": "file:///source", "requested_graph": {"schema_version": 1, "parser_semantics_version": 7}})))
    wire = wire.replace(b'"service":"parser-service"', b'"service":"parser-service","service":"impostor"')
    with pytest.raises(ValueError, match="duplicate JSON field"):
        decode_json(wire)


def test_decode_is_deeply_non_mutating_and_json_is_canonical():
    source = envelope("graph.ready.v1", {"source_uri": "file:///source", "graph": {"uri": "file:///graph.json", "sha256": HASH, "size_bytes": 0, "schema_version": 1, "parser_semantics_version": 7, "graph_fingerprint": HASH}})
    original = deepcopy(source)
    encoded = encode_json(from_mapping(source))
    assert source == original
    assert encoded == encode_json(from_mapping(dict(reversed(list(source.items())))))
    assert encoded == encode_json(decode_json(encoded))


@pytest.mark.parametrize("field,bad", [
    ("schema_version", True), ("parser_semantics_version", True),
    ("schema_version", 2), ("parser_semantics_version", 6),
])
def test_requested_graph_requires_exact_integer_versions(field, bad):
    requested = {"schema_version": 1, "parser_semantics_version": 7}
    requested[field] = bad
    with pytest.raises((TypeError, ValueError)):
        from_mapping(envelope("parser.start.v1", {"source_uri": "file:///source", "requested_graph": requested}))


def test_graph_ready_cannot_embed_canonical_graph_dto():
    graph = {"uri": "file:///graph.json", "sha256": HASH, "size_bytes": 12, "schema_version": 1, "parser_semantics_version": 7, "graph_fingerprint": HASH, "nodes": []}
    with pytest.raises(ValueError, match="extra=.*nodes"):
        from_mapping(envelope("graph.ready.v1", {"source_uri": "file:///source", "graph": graph}))


def test_direct_constructor_validates_producer_and_parser_payload_family():
    with pytest.raises(ValueError):
        Producer("parser-service", "\ud800")
    with pytest.raises(TypeError):
        RequestedGraph(True, 7)
    with pytest.raises(TypeError):
        ParserStart("file:///source", {"schema_version": 1})
    with pytest.raises(ValueError):
        GraphDescriptor("file:///graph", HASH, -1, 1, 7, HASH)
    with pytest.raises(ValueError):
        GraphDescriptor("file:///graph", "A" * 64, 1, 1, 7, HASH)
    with pytest.raises(TypeError):
        GraphReady("file:///source", {"uri": "file:///graph"})
    with pytest.raises(ValueError):
        Failure("metrics", "event-1", "failed", "safe", False)
    with pytest.raises(TypeError):
        Failure("parser", "event-1", "failed", "safe", 0)


def test_direct_envelope_validates_base_producer_and_exact_payload_contract():
    payload = ParserStart("file:///source", RequestedGraph(1, 7))
    fields = dict(event_id="event-1", event_type="parser.start.v1", schema_version=1,
                  occurred_at="2026-10-24T12:00:00Z", correlation_id="analysis-1",
                  causation_id="cause-1", tenant_id="tenant-1")
    with pytest.raises(TypeError):
        EventEnvelope(**fields, producer={"service": "parser-service"}, payload=payload)
    with pytest.raises(ValueError):
        EventEnvelope(**{**fields, "schema_version": 2},
                      producer=Producer("parser-service", "build-1"), payload=payload)
    with pytest.raises(ValueError):
        EventEnvelope(**{**fields, "event_type": "graph.ready.v1"},
                      producer=Producer("parser-service", "build-1"), payload=payload)


@pytest.mark.parametrize("wire", [
    b'{"value":NaN}', b'{"value":Infinity}', b'{"value":-Infinity}',
    '{"event_id":"\\ud800"}', '{"event_id":"\\ud83d\\ude00"}',
])
def test_decode_rejects_nonstandard_constants_and_all_surrogates(wire):
    with pytest.raises(ValueError):
        decode_json(wire)


def test_all_parser_dtos_support_valid_direct_construction():
    producer = Producer("parser-service", "build-😀")
    requested = RequestedGraph(1, 7)
    start = ParserStart("file:///source-😀", requested)
    graph = GraphDescriptor("file:///graph-😀", HASH, 0, 1, 7, HASH)
    ready = GraphReady("file:///source-😀", graph)
    failure = Failure("parser", "event-1", "failed", "safe 😀", False)

    for event_type, payload in (
        ("parser.start.v1", start),
        ("graph.ready.v1", ready),
        ("parser.failed.v1", failure),
    ):
        event = EventEnvelope(
            "event-😀", event_type, 1, "2026-10-24T12:00:00Z",
            "analysis-1", "cause-1", "tenant-1", producer, payload,
        )
        assert decode_json(encode_json(event)) == event


def test_from_mapping_builds_nested_dtos_without_recursion_and_preserves_non_bmp():
    source = envelope(
        "parser.start.v1",
        {"source_uri": "file:///😀", "requested_graph": {
            "schema_version": 1, "parser_semantics_version": 7,
        }},
    )
    source["event_id"] = "event-😀"
    event = from_mapping(source)
    assert type(event.payload) is ParserStart
    assert type(event.payload.requested_graph) is RequestedGraph
    assert decode_json(encode_json(event)).event_id == "event-😀"
