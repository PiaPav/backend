import ast
import inspect
from pathlib import Path
from typing import Protocol

from parser_service.application import ports


EXPECTED_SIGNATURES = {
    "EventPublisher": {"publish": ("self", "event")},
    "InputSignalSource": {"start": ("self", "handler"), "stop": ("self",)},
    "IdempotencyStore": {
        "claim": ("self", "key", "payload_digest", "claim_token", "lease_expires_at"),
        "load": ("self", "key"),
        "record_saved": ("self", "key", "claim_token", "event"),
        "record_failure": ("self", "key", "claim_token", "event"),
        "record_published": ("self", "key", "claim_token"),
    },
    "Clock": {"now": ("self",)},
    "EventIdGenerator": {"new_event_id": ("self",)},
    "SourceResolver": {"materialize": ("self", "source_uri")},
    "GraphStagingArea": {"create_target": ("self", "artifact_key")},
    "GraphArtifactStore": {"save": ("self", "staged_path", "artifact_key")},
    "ParserGateway": {"parse": ("self", "source_path", "output_path")},
}


def test_protocol_surface_and_mutation_claim_tokens_are_exact():
    protocol_names = {
        name for name, value in vars(ports).items()
        if isinstance(value, type) and value.__module__ == ports.__name__ and Protocol in value.__mro__
    }
    assert protocol_names == set(EXPECTED_SIGNATURES)
    for protocol_name, methods in EXPECTED_SIGNATURES.items():
        protocol = getattr(ports, protocol_name)
        public = {name for name in protocol.__dict__ if not name.startswith("_")}
        assert public == set(methods)
        for method_name, parameter_names in methods.items():
            assert tuple(inspect.signature(getattr(protocol, method_name)).parameters) == parameter_names


def test_application_modules_have_only_own_contract_and_stdlib_dependencies():
    application = Path(__file__).parents[1] / "application"
    forbidden = ("metrics_service", "views", "infrastructure", "parser.logic", "metrics.logic")
    violations = []
    for source_path in application.glob("*.py"):
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                statement = ast.unparse(node)
                if any(name in statement for name in forbidden):
                    violations.append(f"{source_path.name}: {statement}")
                if isinstance(node, ast.ImportFrom) and node.level and node.level != 1 and node.module != "contracts":
                    violations.append(f"{source_path.name}: unexpected service import {statement}")
    assert not violations, "forbidden application imports:\n" + "\n".join(violations)
