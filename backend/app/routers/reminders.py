"""Reminders inside one activity (for deadlines, appointments, events, important dates).

A reminder becomes a notification when its time has passed and the user next loads notifications or the dashboard
(see services/reminders.py).
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_owned_activity
from app.models import Activity, Reminder, Task
from app.schemas.reminder import ReminderCreate, ReminderOut, ReminderUpdate
from app.services.common import get_child_or_404
from app.services.history import log_event

router = APIRouter(prefix="/activities/{activity_id}/reminders", tags=["reminders"])


def _check_task(db: Session, activity: Activity, task_id: Optional[int]) -> None:
    """A linked task must belong to THIS activity."""
    if task_id is None:
        return
    found = db.scalar(select(Task.id).where(Task.id == task_id, Task.activity_id == activity.id))
    if found is None:
        raise HTTPException(status_code=404, detail="Task not found in this activity.")


@router.post("", response_model=ReminderOut, status_code=status.HTTP_201_CREATED)
def create_reminder(payload: ReminderCreate, activity: Activity = Depends(get_owned_activity), db: Session = Depends(get_db)):
    _check_task(db, activity, payload.task_id)
    reminder = Reminder(activity_id=activity.id, **payload.model_dump())
    db.add(reminder)
    db.flush()
    log_event(db, activity.id, "REMINDER_CREATED", "reminder", reminder.id, f"Created reminder '{reminder.title}'")
    db.commit()
    db.refresh(reminder)
    return reminder


@router.get("", response_model=List[ReminderOut])
def list_reminders(
    pending_only: bool = Query(default=False, description="Only reminders that have not gone off yet"),
    activity: Activity = Depends(get_owned_activity),
    db: Session = Depends(get_db),
):
    stmt = select(Reminder).where(Reminder.activity_id == activity.id)
    if pending_only:
        stmt = stmt.where(Reminder.is_triggered.is_(False))
    return db.scalars(stmt.order_by(Reminder.remind_at.asc(), Reminder.id.asc())).all()


@router.get("/{reminder_id}", response_model=ReminderOut)
def get_reminder(reminder_id: int, activity: Activity = Depends(get_owned_activity), db: Session = Depends(get_db)):
    return get_child_or_404(db, Reminder, reminder_id, activity.id, "Reminder")


@router.patch("/{reminder_id}", response_model=ReminderOut)
def update_reminder(
    reminder_id: int,
    payload: ReminderUpdate,
    activity: Activity = Depends(get_owned_activity),
    db: Session = Depends(get_db),
):
    reminder = get_child_or_404(db, Reminder, reminder_id, activity.id, "Reminder")
    changes = payload.model_dump(exclude_unset=True)
    if "task_id" in changes:
        _check_task(db, activity, changes["task_id"])
    for field, value in changes.items():
        setattr(reminder, field, value)
    if "remind_at" in changes:
        reminder.is_triggered = False  # rescheduled: it should go off at the new time
    if changes:
        log_event(db, activity.id, "REMINDER_UPDATED", "reminder", reminder.id, f"Updated reminder '{reminder.title}'")
    db.commit()
    db.refresh(reminder)
    return reminder


@router.delete("/{reminder_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_reminder(reminder_id: int, activity: Activity = Depends(get_owned_activity), db: Session = Depends(get_db)):
    reminder = get_child_or_404(db, Reminder, reminder_id, activity.id, "Reminder")
    log_event(db, activity.id, "REMINDER_DELETED", "reminder", reminder.id, f"Deleted reminder '{reminder.title}'")
    db.delete(reminder)
    db.commit()
