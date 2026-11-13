"""Reminder -> notification logic.

There is no background scheduler (that would add a new moving part). Instead, due reminders are turned into
notifications lazily: every time the user loads notifications or the dashboard, all of THEIR reminders whose time has
passed are triggered exactly once. Limitation: a reminder only becomes visible when the app is next used, and no
e-mail / push message is sent.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Activity, Notification, Reminder


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def trigger_due_reminders(db: Session, user_id: int, now: Optional[datetime] = None) -> int:
    """Create one notification for each of the user's due, not yet triggered reminders. Returns how many."""
    now = now or utc_now()
    rows = db.execute(
        select(Reminder, Activity.title)
        .join(Activity, Activity.id == Reminder.activity_id)
        .where(Activity.user_id == user_id, Reminder.is_triggered.is_(False), Reminder.remind_at <= now)
    ).all()
    for reminder, activity_title in rows:
        reminder.is_triggered = True
        db.add(Notification(
            user_id=user_id,
            reminder_id=reminder.id,
            message=f"Reminder: {reminder.title} ({activity_title})"[:300],
        ))
    if rows:
        db.commit()
    return len(rows)
