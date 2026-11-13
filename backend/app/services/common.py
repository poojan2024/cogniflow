"""Small helpers shared by routers."""
from typing import Type, TypeVar

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

T = TypeVar("T")


def like_pattern(text: str) -> str:
    """Turn user search text into a safe ILIKE pattern (escapes % and _ so they match literally)."""
    escaped = text.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def get_child_or_404(db: Session, model: Type[T], item_id: int, activity_id: int, label: str) -> T:
    """Load a task/note/expense that belongs to THIS activity (the activity was already ownership-checked)."""
    item = db.scalar(select(model).where(model.id == item_id, model.activity_id == activity_id))
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{label} not found.")
    return item
