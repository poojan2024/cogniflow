"""Task management inside one activity, with the weighted priority score on every task."""
from dataclasses import asdict
from datetime import date, datetime, timezone
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_owned_activity
from app.models import Activity, Task
from app.schemas.organizer import (
    FactorOut,
    PriorityLabel,
    PriorityOut,
    TaskCreate,
    TaskOut,
    TaskStatus,
    TaskUpdate,
)
from app.services.common import get_child_or_404
from app.services.history import log_event
from app.services.priority import LEVELS, PriorityResult, calculate_priority

router = APIRouter(prefix="/activities/{activity_id}/tasks", tags=["tasks"])


def _priority_out(result: PriorityResult) -> PriorityOut:
    return PriorityOut(
        score=result.score,
        level=result.level,
        calculated_level=result.calculated_level,
        is_overridden=result.is_overridden,
        is_active=result.is_active,
        explanation=result.explanation,
        factors=[FactorOut(**asdict(f)) for f in result.factors],
    )


def _task_out(task: Task, activity: Activity) -> TaskOut:
    """The task plus its priority, calculated now from the task and its activity (nothing is stored)."""
    result = calculate_priority(
        due_date=task.due_date,
        importance=task.importance,
        status=task.status,
        activity_priority=activity.priority,
        today=date.today(),
        manual_priority=task.manual_priority,
    )
    return TaskOut.model_validate(task).model_copy(update={"priority": _priority_out(result)})


@router.post("", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
def create_task(payload: TaskCreate, activity: Activity = Depends(get_owned_activity), db: Session = Depends(get_db)):
    task = Task(activity_id=activity.id, **payload.model_dump())
    if task.status == "COMPLETED":
        task.completed_at = datetime.now(timezone.utc)
    db.add(task)
    db.flush()
    log_event(db, activity.id, "TASK_CREATED", "task", task.id, f"Created task '{task.title}'")
    db.commit()
    db.refresh(task)
    return _task_out(task, activity)


@router.get("", response_model=List[TaskOut])
def list_tasks(
    status_filter: Optional[TaskStatus] = None,
    priority_level: Optional[PriorityLabel] = None,
    sort: Literal["due", "priority"] = "due",
    activity: Activity = Depends(get_owned_activity),
    db: Session = Depends(get_db),
):
    """Filters: ?status_filter=PENDING|IN_PROGRESS|COMPLETED and ?priority_level=CRITICAL|HIGH|MEDIUM|LOW
    (priority_level only matches active, i.e. not completed, tasks).
    Sorting: sort=due (earliest due date first, no date last) or sort=priority (most urgent first, completed last)."""
    stmt = select(Task).where(Task.activity_id == activity.id)
    if status_filter:
        stmt = stmt.where(Task.status == status_filter)
    tasks = db.scalars(stmt.order_by(Task.due_date.asc().nulls_last(), Task.id.asc())).all()

    items = [_task_out(t, activity) for t in tasks]
    if priority_level:
        items = [i for i in items if i.priority.is_active and i.priority.level == priority_level]
    if sort == "priority":
        items.sort(key=lambda i: (not i.priority.is_active, LEVELS.index(i.priority.level), -i.priority.score, i.id))
    return items


@router.get("/{task_id}", response_model=TaskOut)
def get_task(task_id: int, activity: Activity = Depends(get_owned_activity), db: Session = Depends(get_db)):
    return _task_out(get_child_or_404(db, Task, task_id, activity.id, "Task"), activity)


@router.patch("/{task_id}", response_model=TaskOut)
def update_task(
    task_id: int,
    payload: TaskUpdate,
    activity: Activity = Depends(get_owned_activity),
    db: Session = Depends(get_db),
):
    task = get_child_or_404(db, Task, task_id, activity.id, "Task")
    changes = payload.model_dump(exclude_unset=True)
    was_completed = task.status == "COMPLETED"

    for field, value in changes.items():
        setattr(task, field, value)

    if "status" in changes:
        if task.status == "COMPLETED" and not was_completed:
            task.completed_at = datetime.now(timezone.utc)
            log_event(db, activity.id, "TASK_COMPLETED", "task", task.id, f"Completed task '{task.title}'")
        elif task.status != "COMPLETED" and was_completed:
            task.completed_at = None
            log_event(db, activity.id, "TASK_REOPENED", "task", task.id, f"Reopened task '{task.title}'")
    if set(changes) - {"status"}:
        log_event(
            db, activity.id, "TASK_UPDATED", "task", task.id,
            "Updated: " + ", ".join(sorted(set(changes) - {"status"})),
        )

    db.commit()
    db.refresh(task)
    return _task_out(task, activity)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(task_id: int, activity: Activity = Depends(get_owned_activity), db: Session = Depends(get_db)):
    task = get_child_or_404(db, Task, task_id, activity.id, "Task")
    log_event(db, activity.id, "TASK_DELETED", "task", task.id, f"Deleted task '{task.title}'")
    db.delete(task)
    db.commit()
