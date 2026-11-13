"""Builds the assistant's context from the stored data of ONE activity (documents, notes, tasks, deadlines, reminders,
expenses). The caller passes an activity that was already ownership-checked; nothing from other activities, other
users or the user's account (e-mail, name, password hash) is ever included.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import List

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models import Activity, Document, Expense, ExtractedInformation, Note, Reminder, Task
from app.services.assistant_core import ContextBundle, ContextItem, assemble_context, clip
from app.services.priority import calculate_priority

MAX_TASKS = 50
MAX_REMINDERS = 20
MAX_NOTES = 30
MAX_EXPENSES = 100
MAX_DOCUMENTS = 10
NOTE_CHARS = 1500
DOCUMENT_CHARS = 3000
DESCRIPTION_CHARS = 1000
TASK_DESCRIPTION_CHARS = 300
FACT_TYPES = ("DOCUMENT_TYPE", "DEADLINE", "DATE", "AMOUNT", "PERSON", "LOCATION")  # keywords are noise, skipped


def _days_phrase(day: date, today: date) -> str:
    delta = (day - today).days
    if delta > 1:
        return f"{delta} days left"
    if delta == 1:
        return "1 day left"
    if delta == 0:
        return "due today"
    return f"overdue by {-delta} day{'s' if delta < -1 else ''}"


def _utc_text(moment: datetime) -> str:
    moment = moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment.astimezone(timezone.utc)
    return moment.strftime("%Y-%m-%d %H:%M") + " UTC"


def build_items(db: Session, activity: Activity, today: date) -> List[ContextItem]:
    items: List[ContextItem] = []

    # ---- the activity itself
    start = activity.start_date.isoformat() if activity.start_date else "not set"
    deadline = (f"{activity.deadline.isoformat()} ({_days_phrase(activity.deadline, today)})"
                if activity.deadline else "not set")
    items.append(ContextItem(
        "Activity", "activity", activity.title,
        f"[Activity] {activity.title} | type {activity.activity_type} | status {activity.status} | "
        f"priority {activity.priority}/5 | start {start} | deadline {deadline}",
        ("Description: " + clip(activity.description, DESCRIPTION_CHARS)) if activity.description else "",
    ))

    # ---- tasks (open ones first, earliest due date first)
    tasks = db.scalars(
        select(Task).where(Task.activity_id == activity.id)
        .order_by(case((Task.status == "COMPLETED", 1), else_=0), Task.due_date.asc().nulls_last(), Task.id)
        .limit(MAX_TASKS)
    ).all()
    for t in tasks:
        if t.status == "COMPLETED":
            due = f"due {t.due_date.isoformat()}" if t.due_date else "no due date"
            tail = f"importance {t.importance}/5 | completed"
        else:
            result = calculate_priority(
                due_date=t.due_date, importance=t.importance, status=t.status,
                activity_priority=activity.priority, today=today, manual_priority=t.manual_priority)
            due = f"due {t.due_date.isoformat()} ({_days_phrase(t.due_date, today)})" if t.due_date else "no due date"
            tail = f"importance {t.importance}/5 | priority {result.level} (score {result.score:.1f})"
        items.append(ContextItem(
            f"Task {t.id}", "task", t.title,
            f"[Task {t.id}] {t.title} | status {t.status} | {due} | {tail}",
            clip(t.description, TASK_DESCRIPTION_CHARS) if t.description else "",
        ))

    # ---- reminders (not yet triggered first)
    reminders = db.scalars(
        select(Reminder).where(Reminder.activity_id == activity.id)
        .order_by(Reminder.is_triggered, Reminder.remind_at.asc()).limit(MAX_REMINDERS)
    ).all()
    for r in reminders:
        state = "already triggered" if r.is_triggered else "not yet triggered"
        items.append(ContextItem(
            f"Reminder {r.id}", "reminder", r.title,
            f"[Reminder {r.id}] {r.title} | at {_utc_text(r.remind_at)} | {state}",
        ))

    # ---- expenses (total over ALL expenses, list of the newest ones)
    count, total = db.execute(
        select(func.count(), func.coalesce(func.sum(Expense.amount), 0)).where(Expense.activity_id == activity.id)
    ).one()
    if count:
        total_text = f"{Decimal(str(total)).quantize(Decimal('0.01'))}"
        items.append(ContextItem(
            "Expenses", "expense", "Expense total",
            f"[Expenses] Total of {count} expense{'s' if count != 1 else ''}: {total_text}",
        ))
        for e in db.scalars(
            select(Expense).where(Expense.activity_id == activity.id)
            .order_by(Expense.expense_date.desc(), Expense.id.desc()).limit(MAX_EXPENSES)
        ).all():
            amount = Decimal(str(e.amount)).quantize(Decimal("0.01"))
            items.append(ContextItem(
                f"Expense {e.id}", "expense", e.description,
                f"[Expense {e.id}] {e.description} | category {e.category or 'none'} | {amount} | {e.expense_date.isoformat()}",
            ))

    # ---- notes
    for n in db.scalars(
        select(Note).where(Note.activity_id == activity.id).order_by(Note.updated_at.desc(), Note.id.desc()).limit(MAX_NOTES)
    ).all():
        items.append(ContextItem(f"Note {n.id}", "note", n.title, f"[Note {n.id}] {n.title}", clip(n.content, NOTE_CHARS)))

    # ---- documents: stored extracted text and facts only (the original files are never sent)
    for d in db.scalars(
        select(Document).where(Document.activity_id == activity.id, Document.user_id == activity.user_id)
        .order_by(Document.id.desc()).limit(MAX_DOCUMENTS)
    ).all():
        facts = db.execute(
            select(ExtractedInformation.info_type, ExtractedInformation.value)
            .where(ExtractedInformation.document_id == d.id, ExtractedInformation.info_type.in_(FACT_TYPES))
            .order_by(ExtractedInformation.id).limit(15)
        ).all()
        body_parts = []
        if facts:
            body_parts.append("Extracted facts: " + "; ".join(f"{t} {v}" for t, v in facts))
        if d.extracted_text:
            body_parts.append("Text: " + clip(d.extracted_text, DOCUMENT_CHARS))
        elif d.error_message:
            body_parts.append("Problem: " + d.error_message)
        items.append(ContextItem(
            f"Doc {d.id}", "document", d.original_filename,
            f"[Doc {d.id}] {d.original_filename} | status {d.processing_status} | extraction {d.extraction_method}",
            "\n".join(body_parts),
        ))
    return items


def build_context(db: Session, activity: Activity, today: date, max_chars: int) -> ContextBundle:
    return assemble_context(build_items(db, activity, today), today, max_chars)
