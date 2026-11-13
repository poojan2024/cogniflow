"""Schemas for tasks, notes and expenses (everything that lives inside one activity)."""
from datetime import date, datetime
from decimal import Decimal
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

TaskStatus = Literal["PENDING", "IN_PROGRESS", "COMPLETED"]
PriorityLabel = Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"]


def _not_blank(v: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError("This field must not be empty.")
    return v


def _reject_null(model: BaseModel, names) -> None:
    for name in names:
        if name in model.model_fields_set and getattr(model, name) is None:
            raise ValueError(f"{name} cannot be null.")


# ------------------------------------------------------------------- tasks
class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=5000)
    due_date: Optional[date] = None
    importance: int = Field(default=3, ge=1, le=5)
    status: TaskStatus = "PENDING"
    manual_priority: Optional[PriorityLabel] = None

    _strip_title = field_validator("title")(_not_blank)


class TaskUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=5000)
    due_date: Optional[date] = None
    importance: Optional[int] = Field(default=None, ge=1, le=5)
    status: Optional[TaskStatus] = None
    manual_priority: Optional[PriorityLabel] = None  # send null to clear the override

    @field_validator("title")
    @classmethod
    def strip_title(cls, v):
        return v if v is None else _not_blank(v)

    @model_validator(mode="after")
    def required_fields_not_null(self):
        _reject_null(self, ("title", "importance", "status"))
        return self


class FactorOut(BaseModel):
    name: str
    detail: str
    normalized: float  # 0..1
    weight: float
    points: float  # contribution to the 0..100 score


class PriorityOut(BaseModel):
    """Result of the weighted priority algorithm (calculated on request, never stored)."""

    score: float
    level: PriorityLabel  # shown level: the manual override if set, otherwise the calculated level
    calculated_level: PriorityLabel
    is_overridden: bool
    is_active: bool  # False for completed tasks
    explanation: str
    factors: List[FactorOut]


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    activity_id: int
    title: str
    description: Optional[str]
    due_date: Optional[date]
    importance: int
    status: str
    manual_priority: Optional[str]
    completed_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    priority: Optional[PriorityOut] = None  # filled in by the tasks router


# ------------------------------------------------------------------- notes
class NoteCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(default="", max_length=20000)

    _strip_title = field_validator("title")(_not_blank)


class NoteUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    content: Optional[str] = Field(default=None, max_length=20000)

    @field_validator("title")
    @classmethod
    def strip_title(cls, v):
        return v if v is None else _not_blank(v)

    @model_validator(mode="after")
    def required_fields_not_null(self):
        _reject_null(self, ("title", "content"))
        return self


class NoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    activity_id: int
    title: str
    content: str
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------- expenses
class ExpenseCreate(BaseModel):
    description: str = Field(min_length=1, max_length=255)
    category: Optional[str] = Field(default=None, max_length=50)
    amount: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    expense_date: date = Field(default_factory=date.today)

    _strip_description = field_validator("description")(_not_blank)


class ExpenseUpdate(BaseModel):
    description: Optional[str] = Field(default=None, min_length=1, max_length=255)
    category: Optional[str] = Field(default=None, max_length=50)
    amount: Optional[Decimal] = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    expense_date: Optional[date] = None

    @field_validator("description")
    @classmethod
    def strip_description(cls, v):
        return v if v is None else _not_blank(v)

    @model_validator(mode="after")
    def required_fields_not_null(self):
        _reject_null(self, ("description", "amount", "expense_date"))
        return self


class ExpenseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    activity_id: int
    description: str
    category: Optional[str]
    amount: Decimal
    expense_date: date
    created_at: datetime


class ExpenseList(BaseModel):
    items: List[ExpenseOut]
    count: int
    total_amount: Decimal
