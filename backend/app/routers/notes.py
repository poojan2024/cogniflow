"""Notes inside one activity: create, edit, delete, view, search."""
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_owned_activity
from app.models import Activity, Note
from app.schemas.organizer import NoteCreate, NoteOut, NoteUpdate
from app.services.common import get_child_or_404, like_pattern
from app.services.history import log_event

router = APIRouter(prefix="/activities/{activity_id}/notes", tags=["notes"])


@router.post("", response_model=NoteOut, status_code=status.HTTP_201_CREATED)
def create_note(payload: NoteCreate, activity: Activity = Depends(get_owned_activity), db: Session = Depends(get_db)):
    note = Note(activity_id=activity.id, **payload.model_dump())
    db.add(note)
    db.flush()
    log_event(db, activity.id, "NOTE_CREATED", "note", note.id, f"Created note '{note.title}'")
    db.commit()
    db.refresh(note)
    return note


@router.get("", response_model=List[NoteOut])
def list_notes(
    q: Optional[str] = Query(default=None, max_length=100, description="Search in title and content"),
    activity: Activity = Depends(get_owned_activity),
    db: Session = Depends(get_db),
):
    stmt = select(Note).where(Note.activity_id == activity.id)
    if q and q.strip():
        pattern = like_pattern(q)
        stmt = stmt.where(or_(Note.title.ilike(pattern, escape="\\"), Note.content.ilike(pattern, escape="\\")))
    return db.scalars(stmt.order_by(Note.updated_at.desc(), Note.id.desc())).all()


@router.get("/{note_id}", response_model=NoteOut)
def get_note(note_id: int, activity: Activity = Depends(get_owned_activity), db: Session = Depends(get_db)):
    return get_child_or_404(db, Note, note_id, activity.id, "Note")


@router.patch("/{note_id}", response_model=NoteOut)
def update_note(
    note_id: int,
    payload: NoteUpdate,
    activity: Activity = Depends(get_owned_activity),
    db: Session = Depends(get_db),
):
    note = get_child_or_404(db, Note, note_id, activity.id, "Note")
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(note, field, value)
    if changes:
        log_event(db, activity.id, "NOTE_UPDATED", "note", note.id, f"Updated note '{note.title}'")
    db.commit()
    db.refresh(note)
    return note


@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_note(note_id: int, activity: Activity = Depends(get_owned_activity), db: Session = Depends(get_db)):
    note = get_child_or_404(db, Note, note_id, activity.id, "Note")
    log_event(db, activity.id, "NOTE_DELETED", "note", note.id, f"Deleted note '{note.title}'")
    db.delete(note)
    db.commit()
