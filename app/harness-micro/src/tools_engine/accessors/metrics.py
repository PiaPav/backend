import copy
import json
from pathlib import Path
from typing import Any

from tools_engine.interface.tool import (
    InvalidArtifact, InvalidToolArguments, MetricPathNotFound, ProfileNotFound,
)
from tools_engine.models.analysis_context import AnalysisContext


class MetricsAccessor:
    def __init__(self, context: AnalysisContext, profile_id: str):
        self.context = context
        self.profile_id = profile_id

    def prepared(self) -> dict[str, Any]:
        key = f"metrics:{self.profile_id}:v1"
        return self.context.get_or_create_cached(key, self._load)

    def raw(self) -> dict[str, Any]:
        return copy.deepcopy(self.prepared())

    def _load(self) -> dict[str, Any]:
        path = self.context.metrics_profiles.get(self.profile_id)
        if path is None:
            raise ProfileNotFound(details={"profile_id": self.profile_id})
        try:
            value = json.loads(Path(path).read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError
            return value
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
            raise InvalidArtifact(details={
                "artifact": "metrics_profile", "profile_id": self.profile_id,
            }) from None

    def get(self, pointer: str) -> Any:
        tokens = self._tokens(pointer)
        value: Any = self.prepared()
        for token in tokens:
            if isinstance(value, dict):
                if token not in value:
                    self._not_found(pointer)
                value = value[token]
            elif isinstance(value, list):
                if (token != "0" and (not token or token[0] == "0"
                                       or not token.isascii() or not token.isdigit())):
                    self._not_found(pointer)
                length = str(len(value))
                if (len(token) > len(length)
                        or (len(token) == len(length) and token >= length)):
                    self._not_found(pointer)
                index = int(token)
                value = value[index]
            else:
                self._not_found(pointer)
        return copy.deepcopy(value)

    @staticmethod
    def _tokens(pointer: str) -> list[str]:
        if pointer == "":
            return []
        if pointer.startswith("#") or not pointer.startswith("/"):
            raise InvalidToolArguments("METRIC-PATH должен быть JSON Pointer")
        result = []
        for raw in pointer[1:].split("/"):
            token = ""
            index = 0
            while index < len(raw):
                if raw[index] != "~":
                    token += raw[index]
                    index += 1
                    continue
                if index + 1 >= len(raw) or raw[index + 1] not in "01":
                    raise InvalidToolArguments("METRIC-PATH содержит неверное экранирование")
                token += "~" if raw[index + 1] == "0" else "/"
                index += 2
            result.append(token)
        return result

    def _not_found(self, pointer: str) -> None:
        raise MetricPathNotFound(details={
            "profile_id": self.profile_id, "metric_path": pointer,
        })
