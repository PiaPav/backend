import datetime
import json
from typing import Literal, Any

from pydantic import BaseModel
from sqlalchemy import Text, DateTime, String, Integer, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import SQLBase
from .datamanager import DataManager


class LogData(BaseModel):
    unique_id: int
    type: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    event: str
    description: str


def _extract_llm_usage(description: str | None) -> dict[str, Any]:
    """Достаёт поля usage/model/finish_reason из JSON-строки ModelResponse.
    Возвращает пустой dict, если строка пустая или не JSON."""
    if not description:
        return {}
    try:
        payload = json.loads(description)
    except (ValueError, TypeError):
        return {}
    if not isinstance(payload, dict):
        return {}

    usage = payload.get("usage") or {}
    choices = payload.get("choices") or []
    first_choice = choices[0] if choices else {}

    return {
        "llm_model": payload.get("model"),
        "llm_response_id": payload.get("id"),
        "finish_reason": first_choice.get("finish_reason"),
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "total_tokens": usage.get("total_tokens"),
        "prompt_cache_hit_tokens": usage.get("prompt_cache_hit_tokens"),
        "prompt_cache_miss_tokens": usage.get("prompt_cache_miss_tokens"),
    }


class HarnessLogs(SQLBase):
    """Проекты пользователей"""
    __tablename__ = "harness_logs"
    __table_args__ = (
        CheckConstraint(
            "type IN ('DEBUG','INFO','WARNING','ERROR','CRITICAL')",
            name="ck_harness_logs_type",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    unique_id: Mapped[int] = mapped_column(Integer)
    date: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True),
                                                    default=lambda: datetime.datetime.now(datetime.timezone.utc))
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    event: Mapped[str] = mapped_column(String(256))
    description: Mapped[str] = mapped_column(Text)

    # --- новые поля ---
    llm_model: Mapped[str | None] = mapped_column(String(64))
    llm_response_id: Mapped[str | None] = mapped_column(String(128))
    finish_reason: Mapped[str | None] = mapped_column(String(64))
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    total_tokens: Mapped[int | None] = mapped_column(Integer)
    prompt_cache_hit_tokens: Mapped[int | None] = mapped_column(Integer)
    prompt_cache_miss_tokens: Mapped[int | None] = mapped_column(Integer)

    @staticmethod
    async def write_log(data: LogData):
        async with DataManager.session() as session:
            log = HarnessLogs(unique_id=data.unique_id,
                              type=data.type,
                              event=data.event,
                              description=data.description,
                              **_extract_llm_usage(data.description))

            session.add(log)
        return
