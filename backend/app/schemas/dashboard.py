from datetime import date, datetime
from decimal import Decimal
from typing import Dict, List, Optional

from pydantic import BaseModel, field_validator

from app.schemas.reminder import as_utc


class OverviewOut(BaseModel):
    total_activities: int
    active_activities: int
    activities_by_status: Dict[str, int]
    pending_tasks: int  # open tasks: pending or in progress
    completed_tasks: int
    overdue_tasks: int
    open_tasks_by_priority: Dict[str, int]  # CRITICAL / HIGH / MEDIUM / LOW (manual overrides included)


class DeadlineItem(BaseModel):
    kind: str  # "activity" or "task"
    id: int
    title: str
    activity_id: int
    activity_title: str
    due_date: date
    days_left: int


class PriorityTaskItem(BaseModel):
    id: int
    title: str
    activity_id: int
    activity_title: str
    due_date: Optional[date]
    level: str
    score: float
    explanation: str


class RecentDocumentItem(BaseModel):
    id: int
    original_filename: str
    processing_status: str
    activity_id: Optional[int]
    created_at: datetime

    _utc = field_validator("created_at")(as_utc)


class RecentEventItem(BaseModel):
    action: str
    entity_type: str
    details: Optional[str]
    activity_id: int
    activity_title: str
    created_at: datetime

    _utc = field_validator("created_at")(as_utc)


class ReminderItem(BaseModel):
    id: int
    title: str
    remind_at: datetime
    activity_id: int
    activity_title: str

    _utc = field_validator("remind_at")(as_utc)


class ExpenseBreakdownItem(BaseModel):
    label: str
    total: Decimal


class ExpenseSummary(BaseModel):
    total: Decimal
    by_category: List[ExpenseBreakdownItem]
    by_activity: List[ExpenseBreakdownItem]


class AttentionOut(BaseModel):
    unread_notifications: int
    pending_suggestions: int  # documents waiting for the user to confirm / reject an activity suggestion
    documents_needing_review: int  # documents with status NEEDS_REVIEW or FAILED


class DashboardOut(BaseModel):
    today: date
    overview: OverviewOut
    upcoming_deadlines: List[DeadlineItem]
    high_priority_tasks: List[PriorityTaskItem]
    recent_documents: List[RecentDocumentItem]
    recent_activity: List[RecentEventItem]
    upcoming_reminders: List[ReminderItem]
    expenses: ExpenseSummary
    attention: AttentionOut
