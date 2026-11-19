import ast
import json
from pathlib import Path

from metrics_service.contracts import GraphReady as ConsumerGraphReady
from metrics_service.contracts import decode_json as consumer_decode
from parser_service.contracts import GraphReady as ProducerGraphReady
from parser_service.contracts import decode_json as producer_decode
from parser_service.contracts import encode_json as producer_encode


FIXTURE = Path(__file__).parent / "fixtures" / "graph_ready_v1.json"


def test_fixed_producer_fixture_decodes_with_independent_consumer():
    wire = FIXTURE.read_bytes()
    producer = producer_decode(wire)
    consumer = consumer_decode(wire)
    assert type(producer.payload) is ProducerGraphReady
    assert type(consumer.payload) is ConsumerGraphReady
    assert producer_encode(producer) == wire.rstrip(b"\n")
    assert consumer.payload.to_mapping() == producer.payload.to_mapping()


def test_source_index_descriptor_crosses_independent_wire_contracts():
    mapping = producer_decode(FIXTURE.read_bytes()).to_mapping()
    mapping["payload"]["source_index"] = {
        "uri": "file:///artifacts/source-index.json",
        "sha256": "c" * 64,
        "size_bytes": 456,
        "schema_version": 1,
        "project_fingerprint": "d" * 64,
    }
    producer = producer_decode(json.dumps(mapping))
    wire = producer_encode(producer)
    consumer = consumer_decode(wire)
    assert consumer.payload.source_index.to_mapping() == mapping["payload"]["source_index"]


def test_metrics_contracts_do_not_import_parser_service():
    contracts = Path(__file__).parents[1] / "contracts"
    for source_path in contracts.glob("*.py"):
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        imported = [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]
        assert all("parser_service" not in ast.unparse(node) for node in imported)


def test_production_service_packages_are_independent_of_each_other_and_legacy_layers():
    metrics_src = Path(__file__).parents[2]
    parser_src = metrics_src.parents[1] / "parser" / "src"
    violations = []
    for src, service in ((parser_src, "parser_service"), (metrics_src, "metrics_service")):
        for source_path in (src / service).rglob("*.py"):
            if "tests" in source_path.parts:
                continue
            tree = ast.parse(source_path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    statement = ast.unparse(node)
                    other_service = "metrics_service" if service == "parser_service" else "parser_service"
                    blocked = (other_service, "infrastructure", "parser.logic", "metrics.logic")
                    if any(name in statement for name in blocked):
                        violations.append(f"{source_path.relative_to(src)}: {statement}")
    assert not violations, "forbidden production imports:\n" + "\n".join(violations)
