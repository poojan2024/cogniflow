"""The user's notifications. Loading them first turns any due reminders into notifications."""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models import Notification, User
from app.schemas.reminder import NotificationOut, NotificationPage
from app.services.reminders import trigger_due_reminders

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _get_own(db: Session, notification_id: int, user: User) -> Notification:
    notification = db.scalar(select(Notification).where(
        Notification.id == notification_id, Notification.user_id == user.id))
    if notification is None:
        raise HTTPException(status_code=404, detail="Notification not found.")
    return notification


@router.get("", response_model=NotificationPage)
def list_notifications(
    unread_only: bool = False,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    trigger_due_reminders(db, current_user.id)
    base = select(Notification).where(Notification.user_id == current_user.id)
    if unread_only:
        base = base.where(Notification.is_read.is_(False))
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    unread = db.scalar(select(func.count()).select_from(Notification).where(
        Notification.user_id == current_user.id, Notification.is_read.is_(False))) or 0
    items = db.scalars(
        base.order_by(Notification.created_at.desc(), Notification.id.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return NotificationPage(items=items, total=total, unread_count=unread, page=page, page_size=page_size)


@router.post("/read-all")
def mark_all_read(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    result = db.execute(update(Notification).where(
        Notification.user_id == current_user.id, Notification.is_read.is_(False)).values(is_read=True))
    db.commit()
    return {"updated": result.rowcount}


@router.post("/{notification_id}/read", response_model=NotificationOut)
def mark_read(notification_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    notification = _get_own(db, notification_id, current_user)
    notification.is_read = True
    db.commit()
    db.refresh(notification)
    return notification


@router.delete("/{notification_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_notification(notification_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    db.delete(_get_own(db, notification_id, current_user))
    db.commit()
