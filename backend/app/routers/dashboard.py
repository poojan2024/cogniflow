"""Dashboard summary for the logged-in user (one call, all numbers and lists the UI needs)."""
from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models import User
from app.schemas.dashboard import DashboardOut
from app.services.dashboard import build_dashboard
from app.services.reminders import trigger_due_reminders, utc_now

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardOut)
def get_dashboard(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    now = utc_now()
    trigger_due_reminders(db, current_user.id, now)  # so the unread notification count is up to date
    return build_dashboard(db, current_user.id, date.today(), now)
