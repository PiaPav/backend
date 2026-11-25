import json
from pathlib import Path

import pytest

from benchmarks.run_store import save_technical_run
from benchmarks.runners import TechnicalCheck, TechnicalRunEnvelope


def _envelope(run_id: str = "run-1") -> TechnicalRunEnvelope:
    event = {"event_type": "harness.completed.v1"}
    return TechnicalRunEnvelope(run_id, "project", "1.0.0", "a" * 64, "baseline", "b" * 64,
        "offline", "1.0.0", "c" * 64, "overview", "full", 2, 1, "passed", "ack",
        (TechnicalCheck("lifecycle", True),), None, {"issues": [], "strengths": []}, "d" * 64,
        event, 0.5)


def test_store_is_deterministic_and_write_once(tmp_path: Path) -> None:
    output = save_technical_run(_envelope(), tmp_path)
    expected = json.dumps(_envelope().to_dict(), ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False) + "\n"
    assert output.read_text(encoding="utf-8") == expected
    with pytest.raises(FileExistsError):
        save_technical_run(_envelope(), tmp_path)


@pytest.mark.parametrize("run_id", [
    *[f"bad{chr(codepoint)}name" for codepoint in range(32)], "bad\x7fname",
    "../escape", "a/b", "a\\b", ".", "..", "...",
    "D:escape", "C:\\outside", "C:/outside", ":stream",
    "\\\\server\\share", "/rooted", "run.", "run ",
    "bad<name", "bad>name", 'bad"name', "bad|name", "bad?name", "bad*name",
    "CON", "con.txt", "CON .txt", "PRN.log", "aux", "NUL.json", "COM1", "com9.ext",
    "LPT1", "lpt9.txt", "COM¹", "lpt².txt",
])
def test_store_rejects_unsafe_run_id(tmp_path: Path, run_id: str) -> None:
    with pytest.raises(ValueError):
        save_technical_run(_envelope(run_id), tmp_path)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("run_id", ["run-1", "release_2026.11", "com10", "lpt10.txt", "console.txt"])
def test_store_accepts_portable_normal_run_ids(tmp_path: Path, run_id: str) -> None:
    assert save_technical_run(_envelope(run_id), tmp_path).is_file()


def test_store_rejects_existing_file_or_directory(tmp_path: Path) -> None:
    (tmp_path / "run-1").write_text("occupied", encoding="utf-8")
    with pytest.raises(FileExistsError):
        save_technical_run(_envelope(), tmp_path)


def test_store_rejects_link_like_root(tmp_path: Path) -> None:
    actual = tmp_path / "actual"; actual.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(actual, target_is_directory=True)
    except OSError:
        pytest.skip("directory links are unavailable")
    with pytest.raises(ValueError):
        save_technical_run(_envelope(), link)
