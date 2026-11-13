"""Creates activity suggestions for an unassigned document. Suggestions are only stored; nothing is moved
until the user confirms (routers/suggestions.py).

Only the logged-in user's OWN activities are ever considered, so another user's data can never be suggested.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Iterable, List, Optional, Tuple

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import Activity, ActivitySuggestion, Document, ExtractedInformation, Note, Task
from app.services.activity_matching import (
    MAX_SUGGESTIONS,
    MIN_SUGGEST_SCORE,
    ActivityProfile,
    DocumentInfo,
    rank_activities,
)
from app.services.history import log_event

logger = logging.getLogger("cogniflow")

OPEN_STATUSES = ("NOT_STARTED", "ACTIVE", "ON_HOLD")  # finished or cancelled activities are not suggested
MAX_ACTIVITIES = 200
MAX_EXTRA_DOCS = 10
EXTRA_DOC_CHARS = 3000
MAX_TITLES = 30


def build_profiles(db: Session, user_id: int) -> List[ActivityProfile]:
    activities = db.scalars(
        select(Activity)
        .where(Activity.user_id == user_id, Activity.status.in_(OPEN_STATUSES))
        .order_by(Activity.id)
        .limit(MAX_ACTIVITIES)
    ).all()
    profiles = []
    for activity in activities:
        texts = db.scalars(
            select(Document.extracted_text)
            .where(Document.activity_id == activity.id, Document.extracted_text.is_not(None))
            .order_by(Document.id.desc())
            .limit(MAX_EXTRA_DOCS)
        ).all()
        note_titles = db.scalars(select(Note.title).where(Note.activity_id == activity.id).limit(MAX_TITLES)).all()
        task_titles = db.scalars(select(Task.title).where(Task.activity_id == activity.id).limit(MAX_TITLES)).all()
        extra = " ".join([t[:EXTRA_DOC_CHARS] for t in texts] + list(note_titles) + list(task_titles))
        profiles.append(
            ActivityProfile(
                activity_id=activity.id,
                title=activity.title,
                activity_type=activity.activity_type,
                description=activity.description or "",
                start_date=activity.start_date,
                deadline=activity.deadline,
                extra_text=extra,
            )
        )
    return profiles


def document_info(text: str, pairs: Iterable[Tuple[str, str]]) -> DocumentInfo:
    """Build the matching input from the document text and its extracted (info_type, value) pairs."""
    doc_type: Optional[str] = None
    dates: List[date] = []
    for info_type, value in pairs:
        if info_type == "DOCUMENT_TYPE" and doc_type is None:
            doc_type = value
        elif info_type in ("DATE", "DEADLINE"):
            try:
                dates.append(date.fromisoformat(value))
            except ValueError:
                pass
    return DocumentInfo(text=text, doc_type=doc_type, dates=tuple(dates))


def generate_suggestions(db: Session, document: Document, items: Optional[Iterable] = None) -> List[ActivitySuggestion]:
    """Replace the document's PENDING suggestions with fresh ones (best first, at most MAX_SUGGESTIONS).

    Activities the user already rejected for this document are not suggested again.
    Does nothing for a document that is already in an activity or has no text. The caller commits.
    """
    if document.activity_id is not None or not document.extracted_text:
        return []
    if items is None:
        items = db.execute(
            select(ExtractedInformation.info_type, ExtractedInformation.value)
            .where(ExtractedInformation.document_id == document.id)
        ).all()
    info = document_info(document.extracted_text, [(i.info_type, i.value) for i in items])

    db.execute(delete(ActivitySuggestion).where(
        ActivitySuggestion.document_id == document.id, ActivitySuggestion.status == "PENDING"))
    rejected = set(db.scalars(select(ActivitySuggestion.activity_id).where(
        ActivitySuggestion.document_id == document.id, ActivitySuggestion.status == "REJECTED")).all())

    matches = [
        m for m in rank_activities(info, build_profiles(db, document.user_id))
        if m.score >= MIN_SUGGEST_SCORE and m.activity_id not in rejected
    ][:MAX_SUGGESTIONS]

    created = []
    for match in matches:
        suggestion = ActivitySuggestion(
            document_id=document.id, activity_id=match.activity_id, score=match.score,
            explanation=match.explanation, status="PENDING")
        db.add(suggestion)
        created.append(suggestion)
    if matches:
        log_event(db, matches[0].activity_id, "SUGGESTION_GENERATED", "document", document.id,
                  f"Suggested adding '{document.original_filename}' here (score {matches[0].score:.1f}/100). Waiting for confirmation.")
    return created


def safe_generate_suggestions(db: Session, document: Document, items: Optional[Iterable] = None) -> None:
    """Used after a document was processed: a matching problem must never undo or break the processing result."""
    try:
        generate_suggestions(db, document, items)
        db.commit()
    except Exception:
        logger.exception("Activity matching failed for document %s", getattr(document, "id", "?"))
        db.rollback()
