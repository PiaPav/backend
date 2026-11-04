from pathlib import Path

import pytest

from parser_service.adapters import canonical_core
from parser_service.application.errors import InvalidGraphDtoError


def test_parser_adapter_delegates_to_public_api(monkeypatch, tmp_path: Path) -> None:
    source, output = tmp_path / "source", tmp_path / "graph.json"
    calls = []
    monkeypatch.setattr(canonical_core.parser, "parse_project", lambda left, right: calls.append((left, right)) or right)

    assert canonical_core.CanonicalParserGateway().parse(source, output) == output
    assert calls == [(source, output)]


@pytest.mark.parametrize("content", [b"not-json", b"\xff"])
def test_graph_validator_translates_deterministic_decode_errors_safely(tmp_path: Path, content: bytes) -> None:
    artifact = tmp_path / "graph.json"
    artifact.write_bytes(content)

    with pytest.raises(InvalidGraphDtoError, match="^Canonical graph validation failed$"):
        canonical_core.CanonicalGraphValidator().validate(artifact)


def test_graph_validator_translates_contract_error_safely(monkeypatch, tmp_path: Path) -> None:
    artifact = tmp_path / "graph.json"
    artifact.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        canonical_core.graph_dto, "validate_graph_v1",
        lambda value: (_ for _ in ()).throw(ValueError("sensitive contract detail")),
    )

    with pytest.raises(InvalidGraphDtoError, match="^Canonical graph validation failed$"):
        canonical_core.CanonicalGraphValidator().validate(artifact)
