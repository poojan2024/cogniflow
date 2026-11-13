"""Activity suggestions for a document. The system only SUGGESTS; the user decides.

  confirm -> the document is put into the suggested activity
  reject  -> the suggestion is dropped; the document stays unassigned and the user can pick an activity manually
             (PATCH /documents/{id} with activity_id)
Both decisions are written to the activity history.
"""
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user, get_owned_document
from app.models import Activity, ActivitySuggestion, Document, User
from app.schemas.document import DocumentOut
from app.schemas.suggestion import SuggestionOut
from app.services.activity_matching import confidence_label
from app.services.history import log_event
from app.services.suggestions import generate_suggestions

router = APIRouter(prefix="/documents/{document_id}/suggestions", tags=["suggestions"])


def _out(s: ActivitySuggestion) -> SuggestionOut:
    return SuggestionOut(
        id=s.id,
        document_id=s.document_id,
        activity_id=s.activity_id,
        activity_title=s.activity.title,
        activity_type=s.activity.activity_type,
        score=s.score,
        confidence=confidence_label(s.score),
        explanation=s.explanation,
        status=s.status,
        created_at=s.created_at,
        resolved_at=s.resolved_at,
    )


def _list(db: Session, document: Document) -> List[SuggestionOut]:
    rows = db.scalars(select(ActivitySuggestion).where(ActivitySuggestion.document_id == document.id)).all()
    rows.sort(key=lambda s: (s.status != "PENDING", -s.score, s.id))  # pending first, best score first
    return [_out(s) for s in rows]


def _get_suggestion(db: Session, document: Document, suggestion_id: int) -> ActivitySuggestion:
    suggestion = db.scalar(select(ActivitySuggestion).where(
        ActivitySuggestion.id == suggestion_id, ActivitySuggestion.document_id == document.id))
    if suggestion is None:
        raise HTTPException(status_code=404, detail="Suggestion not found.")
    return suggestion


@router.get("", response_model=List[SuggestionOut])
def list_suggestions(document: Document = Depends(get_owned_document), db: Session = Depends(get_db)):
    return _list(db, document)


@router.post("", response_model=List[SuggestionOut])
def refresh_suggestions(document: Document = Depends(get_owned_document), db: Session = Depends(get_db)):
    """Calculate suggestions again (for example after creating a new activity)."""
    if document.activity_id is not None:
        raise HTTPException(status_code=409, detail="This document is already in an activity.")
    if not document.extracted_text:
        raise HTTPException(status_code=409, detail="This document has no extracted text to compare yet.")
    generate_suggestions(db, document)
    db.commit()
    return _list(db, document)


@router.post("/{suggestion_id}/confirm", response_model=DocumentOut)
def confirm_suggestion(
    suggestion_id: int,
    document: Document = Depends(get_owned_document),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    suggestion = _get_suggestion(db, document, suggestion_id)
    if suggestion.status != "PENDING":
        raise HTTPException(status_code=409, detail=f"This suggestion was already {suggestion.status.lower()}.")
    if document.activity_id is not None:
        raise HTTPException(status_code=409, detail="This document is already in an activity.")
    activity = db.scalar(select(Activity).where(
        Activity.id == suggestion.activity_id, Activity.user_id == current_user.id))
    if activity is None:
        raise HTTPException(status_code=404, detail="Activity not found.")

    document.activity_id = activity.id
    suggestion.status = "CONFIRMED"
    suggestion.resolved_at = datetime.now(timezone.utc)
    db.execute(delete(ActivitySuggestion).where(  # the other open suggestions are no longer needed
        ActivitySuggestion.document_id == document.id,
        ActivitySuggestion.id != suggestion.id,
        ActivitySuggestion.status == "PENDING",
    ))
    log_event(db, activity.id, "SUGGESTION_CONFIRMED", "document", document.id,
              f"Confirmed: '{document.original_filename}' belongs to this activity (score {suggestion.score:.1f}/100)")
    log_event(db, activity.id, "DOCUMENT_ASSIGNED", "document", document.id,
              f"Added '{document.original_filename}' to this activity")
    db.commit()
    db.refresh(document)
    return document


@router.post("/{suggestion_id}/reject", response_model=List[SuggestionOut])
def reject_suggestion(
    suggestion_id: int,
    document: Document = Depends(get_owned_document),
    db: Session = Depends(get_db),
):
    """Reject one suggestion. The document is NOT moved. The remaining suggestions (if any) are returned."""
    suggestion = _get_suggestion(db, document, suggestion_id)
    if suggestion.status != "PENDING":
        raise HTTPException(status_code=409, detail=f"This suggestion was already {suggestion.status.lower()}.")
    suggestion.status = "REJECTED"
    suggestion.resolved_at = datetime.now(timezone.utc)
    log_event(db, suggestion.activity_id, "SUGGESTION_REJECTED", "document", document.id,
              f"Rejected: '{document.original_filename}' does not belong to this activity")
    db.commit()
    return _list(db, document)
