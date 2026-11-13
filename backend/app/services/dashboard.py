"""Dashboard data for ONE user. Every query is restricted to the user's own activities / documents / notifications.

The calculations live in dashboard_calc.py (pure, unit-tested); this module runs the database queries that feed them.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Activity,
    ActivityHistory,
    ActivitySuggestion,
    Document,
    Expense,
    Notification,
    Reminder,
    Task,
)
from app.schemas.dashboard import (
    AttentionOut,
    DashboardOut,
    DeadlineItem,
    ExpenseBreakdownItem,
    ExpenseSummary,
    OverviewOut,
    PriorityTaskItem,
    RecentDocumentItem,
    RecentEventItem,
    ReminderItem,
)
from app.services.dashboard_calc import TaskRow, merge_deadlines, summarize_tasks

OPEN_ACTIVITY_STATUSES = ("NOT_STARTED", "ACTIVE", "ON_HOLD")
MAX_OPEN_TASKS = 2000  # safety limit for the priority calculation


def _money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


# ----------------------------------------------------------------- database part
def build_dashboard(db: Session, user_id: int, today: date, now: datetime) -> DashboardOut:
    owned = Activity.user_id == user_id

    total_activities = db.scalar(select(func.count()).select_from(Activity).where(owned)) or 0
    by_status = {s: c for s, c in db.execute(
        select(Activity.status, func.count()).where(owned).group_by(Activity.status)).all()}

    task_rows = [
        TaskRow(*row) for row in db.execute(
            select(Task.id, Task.title, Task.due_date, Task.importance, Task.status, Task.manual_priority,
                   Activity.id, Activity.title, Activity.priority)
            .join(Activity, Activity.id == Task.activity_id)
            .where(owned, Task.status != "COMPLETED").order_by(Task.id).limit(MAX_OPEN_TASKS)
        ).all()
    ]
    completed_tasks = db.scalar(
        select(func.count()).select_from(Task).join(Activity, Activity.id == Task.activity_id)
        .where(owned, Task.status == "COMPLETED")) or 0
    priority_counts, overdue_tasks, high_priority = summarize_tasks(task_rows, today)

    activity_deadlines = db.execute(
        select(Activity.id, Activity.title, Activity.deadline)
        .where(owned, Activity.status.in_(OPEN_ACTIVITY_STATUSES), Activity.deadline.is_not(None))
    ).all()
    deadlines = merge_deadlines(activity_deadlines, task_rows, today)

    recent_docs = db.scalars(
        select(Document).where(Document.user_id == user_id)
        .order_by(Document.created_at.desc(), Document.id.desc()).limit(5)).all()
    recent_events = db.execute(
        select(ActivityHistory, Activity.title).join(Activity, Activity.id == ActivityHistory.activity_id)
        .where(owned).order_by(ActivityHistory.created_at.desc(), ActivityHistory.id.desc()).limit(10)).all()
    reminders = db.execute(
        select(Reminder, Activity.title).join(Activity, Activity.id == Reminder.activity_id)
        .where(owned, Reminder.is_triggered.is_(False), Reminder.remind_at >= now)
        .order_by(Reminder.remind_at.asc(), Reminder.id.asc()).limit(5)).all()

    total_expenses = db.scalar(select(func.sum(Expense.amount)).select_from(Expense)
                               .join(Activity, Activity.id == Expense.activity_id).where(owned))
    category = func.coalesce(Expense.category, "Uncategorized")
    by_category = db.execute(
        select(category, func.sum(Expense.amount)).select_from(Expense)
        .join(Activity, Activity.id == Expense.activity_id).where(owned)
        .group_by(category).order_by(func.sum(Expense.amount).desc()).limit(6)).all()
    by_activity = db.execute(
        select(Activity.title, func.sum(Expense.amount)).select_from(Expense)
        .join(Activity, Activity.id == Expense.activity_id).where(owned)
        .group_by(Activity.id, Activity.title).order_by(func.sum(Expense.amount).desc()).limit(5)).all()

    unread = db.scalar(select(func.count()).select_from(Notification)
                       .where(Notification.user_id == user_id, Notification.is_read.is_(False))) or 0
    pending_suggestions = db.scalar(
        select(func.count(func.distinct(ActivitySuggestion.document_id))).select_from(ActivitySuggestion)
        .join(Document, Document.id == ActivitySuggestion.document_id)
        .where(Document.user_id == user_id, Document.activity_id.is_(None), ActivitySuggestion.status == "PENDING")) or 0
    needs_review = db.scalar(
        select(func.count()).select_from(Document)
        .where(Document.user_id == user_id, Document.processing_status.in_(("NEEDS_REVIEW", "FAILED")))) or 0

    return DashboardOut(
        today=today,
        overview=OverviewOut(
            total_activities=total_activities,
            active_activities=by_status.get("ACTIVE", 0),
            activities_by_status=by_status,
            pending_tasks=len(task_rows),
            completed_tasks=completed_tasks,
            overdue_tasks=overdue_tasks,
            open_tasks_by_priority=priority_counts,
        ),
        upcoming_deadlines=[DeadlineItem(**asdict(d)) for d in deadlines],
        high_priority_tasks=[PriorityTaskItem(**asdict(t)) for t in high_priority],
        recent_documents=[RecentDocumentItem(
            id=d.id, original_filename=d.original_filename, processing_status=d.processing_status,
            activity_id=d.activity_id, created_at=d.created_at) for d in recent_docs],
        recent_activity=[RecentEventItem(
            action=h.action, entity_type=h.entity_type, details=h.details, activity_id=h.activity_id,
            activity_title=title, created_at=h.created_at) for h, title in recent_events],
        upcoming_reminders=[ReminderItem(
            id=r.id, title=r.title, remind_at=r.remind_at, activity_id=r.activity_id, activity_title=title)
            for r, title in reminders],
        expenses=ExpenseSummary(
            total=_money(total_expenses),
            by_category=[ExpenseBreakdownItem(label=label, total=_money(v)) for label, v in by_category],
            by_activity=[ExpenseBreakdownItem(label=label, total=_money(v)) for label, v in by_activity],
        ),
        attention=AttentionOut(
            unread_notifications=unread,
            pending_suggestions=pending_suggestions,
            documents_needing_review=needs_review,
        ),
    )
