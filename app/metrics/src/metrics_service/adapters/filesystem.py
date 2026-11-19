"""Local-filesystem adapters for Metrics Service."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import tempfile
import unicodedata
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from urllib.parse import unquote_to_bytes, urlsplit
from urllib.request import url2pathname

from ..application.errors import (ArtifactConflictError, ArtifactStoreUnavailableError,
                                  GraphNotFoundError, GraphTemporarilyUnavailableError,
                                  StagingUnavailableError, UnsupportedUriSchemeError)
from ..application.models import ArtifactDescriptor

_KEY = re.compile(r"metrics/([0-9a-f]{64})\Z")


def _contained(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _decode_file_path(value: str) -> str:
    if re.search(r"%(?![0-9A-Fa-f]{2})", value) or re.search(r"%(?:2[fF]|5[cC]|00)", value):
        raise UnsupportedUriSchemeError("Graph URI is not a supported local file URI")
    try:
        decoded = unquote_to_bytes(value).decode("utf-8", "strict")
    except (UnicodeError, ValueError) as error:
        raise UnsupportedUriSchemeError("Graph URI is not a supported local file URI") from error
    if ("\0" in decoded or "\\" in decoded or "//" in decoded
            or any(unicodedata.category(character) == "Cc" for character in value + decoded)):
        raise UnsupportedUriSchemeError("Graph URI is not a supported local file URI")
    return decoded


def _fsync_directory(path: Path) -> None:
    """Persist directory entries on POSIX; Windows has no portable directory fsync."""
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class LocalGraphInputResolver:
    def __init__(self, root: Path) -> None:
        self._root = Path(root).resolve(strict=True)

    @contextmanager
    def materialize(self, graph_uri: str) -> Iterator[Path]:
        try:
            if type(graph_uri) is not str or any(unicodedata.category(c) == "Cc" for c in graph_uri):
                raise UnsupportedUriSchemeError("Graph URI is not a supported local file URI")
            parsed = urlsplit(graph_uri)
            if (parsed.scheme.lower() != "file" or parsed.netloc.lower() not in {"", "localhost"}
                    or parsed.query or parsed.fragment):
                raise UnsupportedUriSchemeError("Graph URI is not a supported local file URI")
            raw = _decode_file_path(parsed.path)
            local_path = raw[1:] if os.name == "nt" and re.match(r"^/[A-Za-z]:/", raw) else raw
            path = Path(url2pathname(local_path))
            if not path.is_absolute() or (os.name == "nt" and raw.startswith("//")):
                raise UnsupportedUriSchemeError("Graph URI is not a supported local file URI")
            resolved = path.resolve(strict=True)
            if not _contained(resolved, self._root):
                raise UnsupportedUriSchemeError("Graph URI is outside the configured root")
            if not resolved.is_file():
                raise GraphNotFoundError("Graph artifact is not an available regular file")
        except (UnsupportedUriSchemeError, GraphNotFoundError):
            raise
        except (FileNotFoundError, NotADirectoryError) as error:
            raise GraphNotFoundError("Graph artifact was not found") from error
        except (ValueError, UnicodeError) as error:
            raise UnsupportedUriSchemeError("Graph URI is not a supported local file URI") from error
        except OSError as error:
            raise GraphTemporarilyUnavailableError("Graph artifact is temporarily unavailable") from error
        yield resolved


class LocalMetricsStagingArea:
    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    @contextmanager
    def create_target(self, artifact_key: str) -> Iterator[Path]:
        if _KEY.fullmatch(artifact_key) is None:
            raise StagingUnavailableError("Metrics staging key is invalid")
        path: Path | None = None
        try:
            root = self._root.resolve(strict=True)
            descriptor, name = tempfile.mkstemp(prefix="metrics-", suffix=".json", dir=root)
            os.close(descriptor)
            path = Path(name)
        except OSError as error:
            raise StagingUnavailableError("Metrics staging is temporarily unavailable") from error
        primary: BaseException | None = None
        try:
            yield path
        except BaseException as error:
            primary = error
            raise
        finally:
            if path is not None:
                try:
                    path.unlink(missing_ok=True)
                except OSError as error:
                    if primary is None:
                        raise StagingUnavailableError("Metrics staging cleanup is temporarily unavailable") from error
                    primary.add_note("Metrics staging cleanup was unavailable")


class LocalMetricsArtifactStore:
    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    def save(self, staged_path: Path, artifact_key: str) -> ArtifactDescriptor:
        match = _KEY.fullmatch(artifact_key)
        if match is None:
            raise ArtifactStoreUnavailableError("Metrics artifact key is invalid")
        temporary: Path | None = None
        primary: BaseException | None = None
        try:
            root = self._root.resolve(strict=True)
            directory = root / "metrics"
            directory_existed = directory.exists()
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            directory = directory.resolve(strict=True)
            if not _contained(directory, root):
                raise OSError("artifact directory escaped root")
            if not directory_existed:
                _fsync_directory(root)
            destination = directory / f"{match.group(1)}.json"
            fd, name = tempfile.mkstemp(prefix=".publish-", dir=directory)
            temporary = Path(name)
            hasher, size = hashlib.sha256(), 0
            with os.fdopen(fd, "wb") as target, Path(staged_path).open("rb") as source:
                while chunk := source.read(1024 * 1024):
                    target.write(chunk); hasher.update(chunk); size += len(chunk)
                target.flush(); os.fsync(target.fileno())
            try:
                os.link(temporary, destination)
                _fsync_directory(directory)
            except FileExistsError:
                old_hash, old_size = self._hash(destination)
                if old_hash != hasher.hexdigest() or old_size != size:
                    raise ArtifactConflictError("Metrics artifact already exists with different content")
            return ArtifactDescriptor(destination.as_uri(), hasher.hexdigest(), size)
        except ArtifactConflictError as error:
            primary = error
            raise
        except OSError as error:
            unavailable = ArtifactStoreUnavailableError("Metrics artifact store is temporarily unavailable")
            primary = unavailable
            raise unavailable from error
        except BaseException as error:
            primary = error
            raise
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError as error:
                    if primary is None:
                        raise ArtifactStoreUnavailableError("Metrics artifact cleanup is temporarily unavailable") from error
                    primary.add_note("Metrics artifact cleanup was unavailable")

    @staticmethod
    def _hash(path: Path) -> tuple[str, int]:
        hasher, size = hashlib.sha256(), 0
        before = path.lstat()
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
            raise ArtifactConflictError("Metrics artifact destination is not a regular file")
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        current = os.fstat(descriptor)
        if (not stat.S_ISREG(current.st_mode)
                or (before.st_dev, before.st_ino) != (current.st_dev, current.st_ino)):
            os.close(descriptor)
            raise ArtifactConflictError("Metrics artifact destination is not a regular file")
        with os.fdopen(descriptor, "rb") as source:
            while chunk := source.read(1024 * 1024):
                hasher.update(chunk); size += len(chunk)
        return hasher.hexdigest(), size


__all__ = ["LocalGraphInputResolver", "LocalMetricsArtifactStore", "LocalMetricsStagingArea"]
