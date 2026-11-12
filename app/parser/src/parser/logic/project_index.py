"""Filesystem discovery and local module resolution."""

from __future__ import annotations

import ast
import codecs
from pathlib import Path

from .errors import ProjectNotFoundError, SourceReadError, SourceSyntaxError
from .models import ModuleInfo

IGNORED_DIRECTORIES = {
    "__pycache__",
    ".git",
    ".hg",
    ".svn",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "venv",
    "env",
    "node_modules",
}


class ProjectIndex:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        if not self.root.is_dir():
            raise ProjectNotFoundError(f"Project directory does not exist: {self.root}")
        self.modules: list[ModuleInfo] = []
        self.by_module: dict[str, ModuleInfo] = {}
        self.by_module_candidates: dict[str, tuple[ModuleInfo, ...]] = {}
        self.shadowed_modules: list[tuple[str, ModuleInfo, ModuleInfo]] = []

    @staticmethod
    def _sort_key(path: Path) -> tuple[object, ...]:
        """Stable source order, with conventional entry modules first."""
        relative_parts = path.parts
        stem = path.stem
        conventional = {"main": 0, "models": 1, "interface": 2}
        same_as_package = bool(path.parent.name and stem == path.parent.name)
        return (
            len(relative_parts),
            conventional.get(stem, 3),
            0 if same_as_package else 1,
            tuple(part.casefold() for part in relative_parts),
        )

    def discover(self) -> list[ModuleInfo]:
        paths = [
            path
            for path in self.root.rglob("*.py")
            if not any(
                part in IGNORED_DIRECTORIES or (part.startswith(".") and part != ".")
                for part in path.relative_to(self.root).parts[:-1]
            )
        ]
        paths.sort(key=lambda item: self._sort_key(item.relative_to(self.root)))
        self.modules = [self._parse(path) for path in paths]
        grouped: dict[str, list[ModuleInfo]] = {}
        for module in self.modules:
            grouped.setdefault(module.module, []).append(module)
        self.by_module_candidates = {
            name: tuple(sorted(items, key=self._module_preference))
            for name, items in grouped.items()
        }
        self.by_module = {name: items[0] for name, items in self.by_module_candidates.items()}
        self.shadowed_modules = [
            (name, shadowed, items[0])
            for name, items in sorted(self.by_module_candidates.items())
            for shadowed in items[1:]
        ]
        return self.modules

    @staticmethod
    def _module_preference(module: ModuleInfo) -> tuple[int, str]:
        # Python chooses a regular package over a same-directory module.
        is_package = module.relative_path.name == "__init__.py"
        return (0 if is_package else 1, module.relative_path.as_posix())

    def _parse(self, path: Path) -> ModuleInfo:
        relative = path.relative_to(self.root)
        module_parts = list(relative.with_suffix("").parts)
        if module_parts[-1] == "__init__":
            module_parts.pop()
        module_name = ".".join(module_parts)
        package = ".".join(relative.parent.parts) if relative.parent != Path(".") else ""
        try:
            source_bytes = path.read_bytes()
            source = source_bytes.decode("utf-8-sig")
        except (OSError, UnicodeError) as exc:
            raise SourceReadError(f"Cannot read {path}: {exc}") from exc
        try:
            tree = ast.parse(source, filename=str(path), type_comments=True)
        except SyntaxError as exc:
            raise SourceSyntaxError(path, exc.msg, exc.lineno, exc.offset) from exc
        return ModuleInfo(
            name=path.stem,
            module=module_name,
            package=package,
            relative_path=relative,
            file=path,
            tree=tree,
            source=source,
            source_bytes=source_bytes,
            byte_order_mark_size=(
                len(codecs.BOM_UTF8) if source_bytes.startswith(codecs.BOM_UTF8) else 0
            ),
        )

    def resolve_module(
        self, requested: str, current_package: str = "", level: int = 0
    ) -> str | None:
        if level:
            package_parts = current_package.split(".") if current_package else []
            keep = max(0, len(package_parts) - level + 1)
            requested = ".".join(package_parts[:keep] + ([requested] if requested else []))
        if requested in self.by_module:
            return requested
        if level:
            return None
        # The test project uses its repository-qualified import path while the
        # selected analysis root starts deeper.  Accept only that explicit form,
        # not an arbitrary qualified name which happens to share a suffix.
        candidates = [
            name
            for name in self.by_module
            if requested.endswith(f".{self.root.name}.{name}")
        ]
        return max(candidates, key=lambda item: len(item.split(".")), default=None)
