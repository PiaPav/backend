"""Domain errors raised by the parser."""

from __future__ import annotations

from pathlib import Path


class ParserError(Exception):
    """Base parser error."""


class ProjectNotFoundError(ParserError):
    """The requested project directory does not exist."""


class SourceReadError(ParserError):
    """A Python source file cannot be read."""


class SourceSyntaxError(ParserError):
    """A Python source file contains invalid syntax."""

    def __init__(
        self, path: Path, message: str, line: int | None, column: int | None
    ) -> None:
        self.path = path
        self.line = line
        self.column = column
        location = f"{path}:{line or '?'}:{column or '?'}"
        super().__init__(f"{location}: {message}")


class GraphValidationError(ParserError):
    """The resulting graph does not satisfy its public contract."""
