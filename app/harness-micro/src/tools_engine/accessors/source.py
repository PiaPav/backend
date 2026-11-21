import json
from pathlib import Path, PurePosixPath

from tools_engine.interface.tool import InvalidArtifact, SourceObjectNotFound
from tools_engine.models.source_index_model import SourceFile, SourceIndex


class SourceAccessor:
    def __init__(self, index_path: Path):
        self.index_path = index_path
        self._index: SourceIndex | None = None

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
            if not resolved.is_file():
                raise OSError
        except (OSError, RuntimeError, ValueError) as exc:
            raise InvalidArtifact(details={"artifact": "source_file", "filepath": filepath}) from exc
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
