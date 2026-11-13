from datetime import date, datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ActivityType = Literal["PROJECT", "EXAM", "TRIP", "MEETING", "APPOINTMENT", "EVENT", "PERSONAL", "CUSTOM"]
ActivityStatus = Literal["NOT_STARTED", "ACTIVE", "ON_HOLD", "COMPLETED", "CANCELLED"]


def _clean_title(v: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError("Title must not be empty.")
    return v


class ActivityCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=5000)
    activity_type: ActivityType = "CUSTOM"
    status: ActivityStatus = "ACTIVE"
    priority: int = Field(default=3, ge=1, le=5)  # 1 = lowest, 5 = highest
    start_date: Optional[date] = None
    deadline: Optional[date] = None

    _strip_title = field_validator("title")(_clean_title)

    @model_validator(mode="after")
    def deadline_not_before_start(self):
        if self.start_date and self.deadline and self.deadline < self.start_date:
            raise ValueError("Deadline cannot be before the start date.")
        return self


class ActivityUpdate(BaseModel):
    """PATCH body: only the fields that are sent are changed."""

    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=5000)
    activity_type: Optional[ActivityType] = None
    status: Optional[ActivityStatus] = None
    priority: Optional[int] = Field(default=None, ge=1, le=5)
    start_date: Optional[date] = None
    deadline: Optional[date] = None

    @field_validator("title")
    @classmethod
    def strip_title(cls, v):
        return v if v is None else _clean_title(v)

    @model_validator(mode="after")
    def required_fields_not_null(self):
        for name in ("title", "activity_type", "status", "priority"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null.")
        return self


class ActivityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: Optional[str]
    activity_type: str
    status: str
    priority: int
    start_date: Optional[date]
    deadline: Optional[date]
    created_at: datetime
    updated_at: datetime


class ActivityPage(BaseModel):
    items: List[ActivityOut]
    total: int
    page: int
    page_size: int


class HistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    action: str
    entity_type: str
    entity_id: Optional[int]
    details: Optional[str]
    created_at: datetime


class HistoryPage(BaseModel):
    items: List[HistoryOut]
    total: int
    page: int
    page_size: int
