import json
from dataclasses import asdict, dataclass
from typing import Any, Literal


@dataclass(frozen=True, slots=True)
class Completeness:
    truncated: bool
    total: int
    returned: int


@dataclass(frozen=True, slots=True)
class Diagnostic:
    code: str
    message: str
    details: dict[str, Any]
    retryable: bool


@dataclass(frozen=True, slots=True)
class ToolResult:
    status: Literal["success", "error"]
    profile_id: str | None
    result: Any
    completeness: Completeness
    diagnostics: tuple[Diagnostic, ...]

    @classmethod
    def success(
        cls, result: Any, *, profile_id: str | None = None,
        completeness: Completeness | None = None,
    ) -> "ToolResult":
        return cls(
            status="success",
            profile_id=profile_id,
            result=result,
            completeness=completeness or Completeness(False, 1, 1),
            diagnostics=(),
        )

    @classmethod
    def failure(cls, error: "ToolError") -> "ToolResult":
        from tools_engine.interface.tool import ToolError

        if not isinstance(error, ToolError):
            raise TypeError("error must be ToolError")
        return cls(
            status="error",
            profile_id=None,
            result=None,
            completeness=Completeness(False, 0, 0),
            diagnostics=(Diagnostic(error.code, error.message, error.details, error.retryable),),
        )

    def to_json(self) -> str:
        return json.dumps(
            asdict(self), ensure_ascii=False, separators=(",", ":"), sort_keys=True
        )

    def utf8_size(self) -> int:
        return len(self.to_json().encode("utf-8"))
