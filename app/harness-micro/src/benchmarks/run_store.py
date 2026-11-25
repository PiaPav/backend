"""Write-once persistence for the limited technical-run envelope."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path, PurePosixPath, PureWindowsPath

import jsonschema

from benchmarks.runners.technical_run import TechnicalRunEnvelope


_WINDOWS_FORBIDDEN = frozenset('<>:"/\\|?*')
_WINDOWS_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{number}" for number in range(1, 10)}
    | {f"LPT{number}" for number in range(1, 10)}
    | {f"COM{number}" for number in "¹²³"}
    | {f"LPT{number}" for number in "¹²³"}
)


def _validate_run_id(run_id: str) -> None:
    """Require one path component that is portable across Windows and POSIX."""
    windows_path = PureWindowsPath(run_id)
    posix_path = PurePosixPath(run_id)
    reserved_basename = run_id.split(".", 1)[0].rstrip(" .").upper()
    if (not run_id or run_id in {".", ".."} or run_id[-1] in {".", " "}
            or any(character in _WINDOWS_FORBIDDEN or ord(character) < 32
                   or ord(character) == 127 for character in run_id)
            or reserved_basename in _WINDOWS_RESERVED
            or windows_path.drive or windows_path.root or windows_path.is_absolute()
            or posix_path.is_absolute() or len(windows_path.parts) != 1
            or len(posix_path.parts) != 1):
        raise ValueError("run_id must be a portable path component")


def _link_like(path: Path) -> bool:
    if path.is_symlink():
        return True
    junction = getattr(path, "is_junction", None)
    return bool((junction is not None and junction()) or
                (getattr(path.lstat(), "st_file_attributes", 0) & 0x400))


def _ordinary_directory(path: Path, name: str) -> None:
    try:
        if _link_like(path) or not path.is_dir():
            raise ValueError(f"{name} must be an existing ordinary directory")
    except OSError as error:
        raise ValueError(f"cannot inspect {name}") from error


def _contained_ordinary(path: Path, root: Path, *, directory: bool) -> bool:
    try:
        mode = path.lstat().st_mode
        ordinary = stat.S_ISDIR(mode) if directory else stat.S_ISREG(mode)
        return ordinary and not _link_like(path) and path.resolve(strict=True).parent == root
    except OSError:
        return False


def _safe_cleanup(target: Path, output: Path, root: Path) -> None:
    """Remove only the exact ordinary artifacts created beneath the verified root."""
    if not _contained_ordinary(target, root, directory=True):
        return
    if output.exists() and not _contained_ordinary(output, target.resolve(strict=True), directory=False):
        return
    try:
        if output.exists():
            output.unlink()
        target.rmdir()
    except OSError:
        pass


def save_technical_run(envelope: TechnicalRunEnvelope, runs_root: Path) -> Path:
    """Validate and exclusively create ``<runs_root>/<run_id>/technical_run.json``."""
    if not isinstance(envelope, TechnicalRunEnvelope):
        raise TypeError("envelope must be a TechnicalRunEnvelope")
    run_id = envelope.run_id
    _validate_run_id(run_id)
    runs_root = Path(runs_root)
    _ordinary_directory(runs_root, "runs_root")
    root = runs_root.resolve(strict=True)
    payload = envelope.to_dict()
    schema_path = Path(__file__).resolve().parent / "schemas" / "technical_run.schema.json"
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(schema).validate(payload)
        encoded = (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                              allow_nan=False) + "\n").encode("utf-8")
    except (OSError, UnicodeError, json.JSONDecodeError, jsonschema.ValidationError) as error:
        raise ValueError("invalid technical run envelope") from error

    target = root / run_id
    if target.parent != root:
        raise ValueError("technical run target escaped runs_root")
    if target.exists() or target.is_symlink():
        raise FileExistsError("technical run already exists")
    created = False
    output = target / "technical_run.json"
    try:
        target.mkdir()
        created = True
        if not _contained_ordinary(target, root, directory=True):
            raise ValueError("technical run directory escaped runs_root")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(output, flags, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                descriptor = -1
                stream.write(encoded)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        if (not _contained_ordinary(target, root, directory=True)
                or not _contained_ordinary(output, target.resolve(strict=True), directory=False)):
            raise ValueError("technical run output escaped runs_root")
        return output
    except Exception:
        if created:
            _safe_cleanup(target, output, root)
        raise


__all__ = ["save_technical_run"]
