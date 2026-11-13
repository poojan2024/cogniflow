"""Activity management. Every query is scoped to the logged-in user."""
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user, get_owned_activity
from app.models import Activity, ActivityHistory, User
from app.schemas.activity import (
    ActivityCreate,
    ActivityOut,
    ActivityPage,
    ActivityType,
    ActivityStatus,
    ActivityUpdate,
    HistoryPage,
)
from app.services.common import like_pattern
from app.services.history import log_event

router = APIRouter(prefix="/activities", tags=["activities"])

SORT_COLUMNS = {
    "created": Activity.created_at.desc(),
    "deadline": Activity.deadline.asc().nulls_last(),
    "priority": Activity.priority.desc(),
    "title": func.lower(Activity.title).asc(),
}


@router.post("", response_model=ActivityOut, status_code=status.HTTP_201_CREATED)
def create_activity(
    payload: ActivityCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    activity = Activity(user_id=current_user.id, **payload.model_dump())
    db.add(activity)
    db.flush()  # assigns activity.id so the history row can reference it
    log_event(db, activity.id, "ACTIVITY_CREATED", "activity", activity.id, f"Created '{activity.title}'")
    db.commit()
    db.refresh(activity)
    return activity


@router.get("", response_model=ActivityPage)
def list_activities(
    q: Optional[str] = Query(default=None, max_length=100, description="Search in title and description"),
    activity_type: Optional[ActivityType] = None,
    status_filter: Optional[ActivityStatus] = Query(default=None, alias="status"),
    sort: Literal["created", "deadline", "priority", "title"] = "created",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(Activity).where(Activity.user_id == current_user.id)
    if q and q.strip():
        pattern = like_pattern(q)
        stmt = stmt.where(
            or_(Activity.title.ilike(pattern, escape="\\"), Activity.description.ilike(pattern, escape="\\"))
        )
    if activity_type:
        stmt = stmt.where(Activity.activity_type == activity_type)
    if status_filter:
        stmt = stmt.where(Activity.status == status_filter)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(
        stmt.order_by(SORT_COLUMNS[sort], Activity.id.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return ActivityPage(items=items, total=total, page=page, page_size=page_size)


@router.get("/{activity_id}", response_model=ActivityOut)
def get_activity(activity: Activity = Depends(get_owned_activity)):
    return activity


@router.patch("/{activity_id}", response_model=ActivityOut)
def update_activity(
    payload: ActivityUpdate,
    activity: Activity = Depends(get_owned_activity),
    db: Session = Depends(get_db),
):
    changes = payload.model_dump(exclude_unset=True)

    # The dates must stay consistent after merging the change with the stored values.
    new_start = changes.get("start_date", activity.start_date)
    new_deadline = changes.get("deadline", activity.deadline)
    if new_start and new_deadline and new_deadline < new_start:
        raise HTTPException(status_code=422, detail="Deadline cannot be before the start date.")

    for field, value in changes.items():
        setattr(activity, field, value)
    if changes:
        log_event(db, activity.id, "ACTIVITY_UPDATED", "activity", activity.id, "Updated: " + ", ".join(sorted(changes)))
    db.commit()
    db.refresh(activity)
    return activity


@router.delete("/{activity_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_activity(activity: Activity = Depends(get_owned_activity), db: Session = Depends(get_db)):
    """Deletes the activity and everything inside it (tasks, notes, expenses, ...). The UI must ask for confirmation."""
    db.delete(activity)
    db.commit()


@router.get("/{activity_id}/history", response_model=HistoryPage)
def activity_history(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    activity: Activity = Depends(get_owned_activity),
    db: Session = Depends(get_db),
):
    base = select(ActivityHistory).where(ActivityHistory.activity_id == activity.id)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    items = db.scalars(
        base.order_by(ActivityHistory.created_at.desc(), ActivityHistory.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return HistoryPage(items=items, total=total, page=page, page_size=page_size)
