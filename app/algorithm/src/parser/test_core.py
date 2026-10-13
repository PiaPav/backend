import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from parser import parse_project, starter


def test_parse_project_is_atomic_deterministic_and_keeps_starter_semantics(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "sample.py").write_text("def f(x):\n    return x + 1\n", encoding="utf-8")

    first = parse_project(source, tmp_path / "first.json")
    second = parse_project(source, tmp_path / "second.json")

    assert first == first.resolve()
    assert first.read_bytes() == second.read_bytes()
    assert json.loads(first.read_text(encoding="utf-8")) == starter(source)


def test_parse_project_requires_paths(tmp_path: Path) -> None:
    with pytest.raises(TypeError):
        parse_project(str(tmp_path), tmp_path / "graph.json")  # type: ignore[arg-type]


def test_parse_project_removes_temporary_file_when_replace_fails(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "sample.py").write_text("value = 1\n", encoding="utf-8")
    target = tmp_path / "graph.json"
    target.write_text("old graph", encoding="utf-8")

    with patch("parser.core.os.replace", side_effect=OSError("injected failure")):
        with pytest.raises(OSError, match="injected failure"):
            parse_project(source, target)

    assert target.read_text(encoding="utf-8") == "old graph"
    assert not list(tmp_path.glob(".graph.json.*"))


def test_public_parser_does_not_import_source_index() -> None:
    assert "parser.logic.source_index" not in sys.modules
