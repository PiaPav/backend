import json
import os
import stat
from pathlib import Path, PurePosixPath

from tools_engine.interface.tool import InvalidArtifact, SourceObjectNotFound
from tools_engine.models.source_index_model import SourceFile, SourceIndex


class SourceAccessor:
    def __init__(self, index_path: Path):
        self.index_path = index_path
        self._index: SourceIndex | None = None
        self._resolved_stats: dict[str, os.stat_result] = {}

    def load_index(self) -> SourceIndex:
        if self._index is not None:
            return self._index
        try:
            raw = json.loads(self.index_path.read_text(encoding="utf-8"))
            self._index = SourceIndex.from_dict(raw)
        except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise InvalidArtifact(details={"artifact": "source_index"}) from exc
        return self._index

    @staticmethod
    def _validate_key(filepath: str) -> PurePosixPath:
        if not filepath or "\\" in filepath:
            raise SourceObjectNotFound(details={"filepath": filepath})
        path = PurePosixPath(filepath)
        if path.is_absolute() or ".." in path.parts or ":" in path.parts[0]:
            raise SourceObjectNotFound(details={"filepath": filepath})
        return path

    def resolve_file(self, filepath: str) -> tuple[SourceIndex, SourceFile, Path]:
        path = self._validate_key(filepath)
        index = self.load_index()
        source_file = index.files.get(filepath)
        if source_file is None:
            raise SourceObjectNotFound(details={"filepath": filepath})
        if path.suffix != ".py":
            raise InvalidArtifact(details={"artifact": "source_index", "filepath": filepath})
        if source_file.relative_path != filepath:
            raise InvalidArtifact(details={"artifact": "source_index", "filepath": filepath})
        try:
            root = Path(index.project.root).resolve(strict=True)
            resolved = root.joinpath(*path.parts).resolve(strict=True)
            resolved.relative_to(root)
            resolved_stat = resolved.stat()
            if not stat.S_ISREG(resolved_stat.st_mode):
                raise OSError
        except (OSError, RuntimeError, ValueError) as exc:
            raise InvalidArtifact(details={"artifact": "source_file", "filepath": filepath}) from exc
        self._resolved_stats[filepath] = resolved_stat
        return index, source_file, resolved

    @staticmethod
    def read_text(source_file: SourceFile, resolved: Path) -> str:
        try:
            return resolved.read_text(encoding=source_file.encoding)
        except (LookupError, OSError, UnicodeError) as exc:
            raise InvalidArtifact(
                details={"artifact": "source_file", "filepath": source_file.relative_path}
            ) from exc

    @staticmethod
    def read_bytes(resolved: Path, start: int, size: int, filepath: str) -> bytes:
        try:
            with resolved.open("rb") as stream:
                stream.seek(start)
                data = stream.read(size)
        except (OSError, ValueError) as exc:
            raise InvalidArtifact(details={"artifact": "source_file", "filepath": filepath}) from exc
        if len(data) != size:
            raise InvalidArtifact(details={"artifact": "source_file", "filepath": filepath})
        return data

    def read_line_range(
        self, source_file: SourceFile, resolved: Path, start: int, end: int, limit: int,
    ) -> tuple[list[dict[str, object]], int]:
        filepath = source_file.relative_path
        invalid_details = {"artifact": "source_file", "filepath": filepath}
        descriptor: int | None = None
        try:
            if type(limit) is not int or limit <= 0:
                raise InvalidArtifact(details={"artifact": "rules_config"})

            index = self.load_index()
            root = Path(index.project.root).resolve(strict=True)
            candidate = root.joinpath(*self._validate_key(filepath).parts)
            expected_stat = self._resolved_stats.get(filepath)
            if expected_stat is None:
                raise InvalidArtifact(details=invalid_details)

            flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(candidate, flags)
            opened_stat = os.fstat(descriptor)
            if (
                not stat.S_ISREG(opened_stat.st_mode)
                or opened_stat.st_size != source_file.size_bytes
                or not os.path.samestat(opened_stat, expected_stat)
            ):
                raise InvalidArtifact(details=invalid_details)

            self._validate_open_file(root, candidate, opened_stat, invalid_details)
            lines: list[dict[str, object]] = []
            total = 0
            with os.fdopen(
                descriptor, "r", encoding=source_file.encoding, newline=None
            ) as stream:
                descriptor = None
                for total, line in enumerate(stream, 1):
                    if start <= total <= end and len(lines) < limit:
                        if line.endswith("\n"):
                            line = line[:-1]
                        lines.append({"line_number": total, "content": line})
                final_stat = os.fstat(stream.fileno())
                if (
                    final_stat.st_size != source_file.size_bytes
                    or not os.path.samestat(final_stat, opened_stat)
                ):
                    raise InvalidArtifact(details=invalid_details)
                self._validate_open_file(root, candidate, final_stat, invalid_details)
        except InvalidArtifact:
            raise
        except (LookupError, OSError, RuntimeError, UnicodeError, ValueError) as exc:
            raise InvalidArtifact(details=invalid_details) from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
        return lines, total

    @staticmethod
    def _validate_open_file(
        root: Path,
        candidate: Path,
        descriptor_stat: os.stat_result,
        invalid_details: dict[str, str],
    ) -> None:
        try:
            current_root = root.resolve(strict=True)
            current = candidate.resolve(strict=True)
            current.relative_to(current_root)
            current_stat = current.stat()
            if not os.path.samestat(current_stat, descriptor_stat):
                raise OSError
        except (OSError, RuntimeError, ValueError) as exc:
            raise InvalidArtifact(details=invalid_details) from exc
