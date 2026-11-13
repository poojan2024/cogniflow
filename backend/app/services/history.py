"""Activity history (audit trail). Rows are added to the caller's transaction and committed with the change itself."""
from typing import Optional

from sqlalchemy.orm import Session

from app.models import ActivityHistory


def log_event(
    db: Session,
    activity_id: int,
    action: str,
    entity_type: str,
    entity_id: Optional[int] = None,
    details: Optional[str] = None,
) -> None:
    db.add(
        ActivityHistory(
            activity_id=activity_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=(details or "")[:500] or None,
        )
    )
