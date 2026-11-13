from datetime import datetime, timezone
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _require_timezone(v: datetime) -> datetime:
    """Reminder times must say which time zone they are in (for example 2026-10-12T09:00:00+05:30). Stored as UTC."""
    if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
        raise ValueError("Include a time zone offset, for example 2026-10-12T09:00:00+05:30")
    return v.astimezone(timezone.utc)


def _as_utc(v: datetime) -> datetime:
    """SQLite returns naive datetimes; they are always UTC here."""
    return v if v.tzinfo else v.replace(tzinfo=timezone.utc)


as_utc = _as_utc  # public name, also used by the dashboard schema


class ReminderCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    remind_at: datetime
    task_id: Optional[int] = None  # optional link to one of this activity's tasks

    @field_validator("title")
    @classmethod
    def strip_title(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Title must not be empty.")
        return v

    _tz = field_validator("remind_at")(_require_timezone)


class ReminderUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    remind_at: Optional[datetime] = None
    task_id: Optional[int] = None  # send null to unlink

    @field_validator("title")
    @classmethod
    def strip_title(cls, v):
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("Title must not be empty.")
        return v

    @field_validator("remind_at")
    @classmethod
    def tz(cls, v):
        return v if v is None else _require_timezone(v)

    @model_validator(mode="after")
    def required_fields_not_null(self):
        for name in ("title", "remind_at"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null.")
        return self


class ReminderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    activity_id: int
    task_id: Optional[int]
    title: str
    remind_at: datetime
    is_triggered: bool
    created_at: datetime

    _utc = field_validator("remind_at", "created_at")(_as_utc)


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    reminder_id: Optional[int]
    message: str
    is_read: bool
    created_at: datetime

    _utc = field_validator("created_at")(_as_utc)


class NotificationPage(BaseModel):
    items: List[NotificationOut]
    total: int
    unread_count: int
    page: int
    page_size: int
