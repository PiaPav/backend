from pathlib import Path

import pytest

from parser_service.adapters import canonical_core
from parser_service.application.errors import InvalidGraphDtoError, InvalidSourceIndexError


def test_parser_adapter_delegates_to_public_api(monkeypatch, tmp_path: Path) -> None:
    source, output, source_index = tmp_path / "source", tmp_path / "graph.json", tmp_path / "source-index.json"
    calls = []
    monkeypatch.setattr(
        canonical_core.parser, "parse_project_with_source_index",
        lambda first, second, third: calls.append((first, second, third)) or (second, third),
    )

    assert canonical_core.CanonicalParserGateway().parse(source, output, source_index) == (output, source_index)
    assert calls == [(source, output, source_index)]


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


def test_source_index_validator_returns_project_fingerprint(tmp_path: Path) -> None:
    fingerprint = "a" * 64
    artifact = tmp_path / "source-index.json"
    artifact.write_text(
        '{"schema_version":1,"project":{"root":"/source","fingerprint":"' + fingerprint
        + '\",\"file_count\":0},\"files_by_name\":{},\"files\":{},\"symbols\":{},\"lookup\":{}}',
        encoding="utf-8",
    )
    assert canonical_core.CanonicalGraphValidator().validate_source_index(artifact) == fingerprint


def test_source_index_validator_rejects_malformed_index_safely(tmp_path: Path) -> None:
    artifact = tmp_path / "source-index.json"
    artifact.write_text("{}", encoding="utf-8")
    with pytest.raises(InvalidSourceIndexError, match="^Canonical source index validation failed$"):
        canonical_core.CanonicalGraphValidator().validate_source_index(artifact)
