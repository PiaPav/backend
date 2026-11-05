"""Local-filesystem adapters for Parser Service.

The configured roots are trust boundaries; supplied URIs and artifact keys never
select paths outside them.
"""

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
                                  SourceNotFoundError, SourceTemporarilyUnavailableError,
                                  StagingUnavailableError, UnsupportedUriSchemeError)
from ..application.models import ArtifactDescriptor

_KEY = re.compile(r"graph/([0-9a-f]{64})\Z")


def _contained(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _decode_file_path(value: str) -> str:
    if re.search(r"%(?![0-9A-Fa-f]{2})", value):
        raise UnsupportedUriSchemeError("Source URI is not a supported local file URI")
    if re.search(r"%(?:2[fF]|5[cC]|00)", value):
        raise UnsupportedUriSchemeError("Source URI is not a supported local file URI")
    try:
        decoded = unquote_to_bytes(value).decode("utf-8", "strict")
    except (UnicodeError, ValueError) as error:
        raise UnsupportedUriSchemeError("Source URI is not a supported local file URI") from error
    if ("\0" in decoded or "\\" in decoded or "//" in decoded
            or any(unicodedata.category(character) == "Cc" for character in value + decoded)):
        raise UnsupportedUriSchemeError("Source URI is not a supported local file URI")
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


class LocalSourceResolver:
    def __init__(self, root: Path) -> None:
        self._root = Path(root).resolve(strict=True)

    @contextmanager
    def materialize(self, source_uri: str) -> Iterator[Path]:
        try:
            if type(source_uri) is not str or any(unicodedata.category(c) == "Cc" for c in source_uri):
                raise UnsupportedUriSchemeError("Source URI is not a supported local file URI")
            parsed = urlsplit(source_uri)
            if (parsed.scheme.lower() != "file" or parsed.netloc.lower() not in {"", "localhost"}
                    or parsed.query or parsed.fragment):
                raise UnsupportedUriSchemeError("Source URI is not a supported local file URI")
            raw = _decode_file_path(parsed.path)
            local_path = raw[1:] if os.name == "nt" and re.match(r"^/[A-Za-z]:/", raw) else raw
            path = Path(url2pathname(local_path))
            if not path.is_absolute() or (os.name == "nt" and raw.startswith("//")):
                raise UnsupportedUriSchemeError("Source URI is not a supported local file URI")
            resolved = path.resolve(strict=True)
            if not _contained(resolved, self._root):
                raise UnsupportedUriSchemeError("Source URI is outside the configured root")
            if not resolved.is_dir():
                raise SourceNotFoundError("Parser source is not an available directory")
        except (UnsupportedUriSchemeError, SourceNotFoundError):
            raise
        except (FileNotFoundError, NotADirectoryError) as error:
            raise SourceNotFoundError("Parser source was not found") from error
        except (ValueError, UnicodeError) as error:
            raise UnsupportedUriSchemeError("Source URI is not a supported local file URI") from error
        except OSError as error:
            raise SourceTemporarilyUnavailableError("Parser source is temporarily unavailable") from error
        yield resolved


class LocalGraphStagingArea:
    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    @contextmanager
    def create_target(self, artifact_key: str) -> Iterator[Path]:
        if _KEY.fullmatch(artifact_key) is None:
            raise StagingUnavailableError("Graph staging key is invalid")
        path: Path | None = None
        try:
            root = self._root.resolve(strict=True)
            descriptor, name = tempfile.mkstemp(prefix="graph-", suffix=".json", dir=root)
            os.close(descriptor)
            path = Path(name)
        except OSError as error:
            raise StagingUnavailableError("Graph staging is temporarily unavailable") from error
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
                        raise StagingUnavailableError("Graph staging cleanup is temporarily unavailable") from error
                    primary.add_note("Graph staging cleanup was unavailable")


class LocalGraphArtifactStore:
    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    def save(self, staged_path: Path, artifact_key: str) -> ArtifactDescriptor:
        match = _KEY.fullmatch(artifact_key)
        if match is None:
            raise ArtifactStoreUnavailableError("Graph artifact key is invalid")
        digest_name = match.group(1)
        temporary: Path | None = None
        primary: BaseException | None = None
        try:
            root = self._root.resolve(strict=True)
            destination_dir = root / "graph"
            directory_existed = destination_dir.exists()
            destination_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            destination_dir = destination_dir.resolve(strict=True)
            if not _contained(destination_dir, root):
                raise OSError("artifact directory escaped root")
            if not directory_existed:
                _fsync_directory(root)
            destination = destination_dir / f"{digest_name}.json"
            fd, name = tempfile.mkstemp(prefix=".publish-", dir=destination_dir)
            temporary = Path(name)
            hasher, size = hashlib.sha256(), 0
            with os.fdopen(fd, "wb") as target, Path(staged_path).open("rb") as source:
                while chunk := source.read(1024 * 1024):
                    target.write(chunk)
                    hasher.update(chunk)
                    size += len(chunk)
                target.flush()
                os.fsync(target.fileno())
            try:
                os.link(temporary, destination)
                _fsync_directory(destination_dir)
            except FileExistsError:
                existing_hash, existing_size = self._hash(destination)
                if existing_hash != hasher.hexdigest() or existing_size != size:
                    raise ArtifactConflictError("Graph artifact already exists with different content")
            return ArtifactDescriptor(destination.as_uri(), hasher.hexdigest(), size)
        except ArtifactConflictError as error:
            primary = error
            raise
        except OSError as error:
            unavailable = ArtifactStoreUnavailableError("Graph artifact store is temporarily unavailable")
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
                        raise ArtifactStoreUnavailableError("Graph artifact cleanup is temporarily unavailable") from error
                    primary.add_note("Graph artifact cleanup was unavailable")

    @staticmethod
    def _hash(path: Path) -> tuple[str, int]:
        hasher, size = hashlib.sha256(), 0
        before = path.lstat()
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
            raise ArtifactConflictError("Graph artifact destination is not a regular file")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        current = os.fstat(descriptor)
        if (not stat.S_ISREG(current.st_mode)
                or (before.st_dev, before.st_ino) != (current.st_dev, current.st_ino)):
            os.close(descriptor)
            raise ArtifactConflictError("Graph artifact destination is not a regular file")
        with os.fdopen(descriptor, "rb") as source:
            while chunk := source.read(1024 * 1024):
                hasher.update(chunk)
                size += len(chunk)
        return hasher.hexdigest(), size


__all__ = ["LocalGraphArtifactStore", "LocalGraphStagingArea", "LocalSourceResolver"]
