"""Global search across ONE user's data. Every query is restricted to the user's own rows:
activities and documents by user_id, everything else through the owning activity.

Method: case-insensitive substring match (SQL ILIKE). That is simple and fine at personal-organizer scale.
Honest limit: no ranking by relevance and no stemming; on very large data a PostgreSQL trigram or full-text
index would be the next step.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import Activity, Document, Expense, ExtractedInformation, Note, Task
from app.services.common import like_pattern
from app.services.snippets import make_snippet

SEARCH_TYPES = ("activities", "documents", "extracted", "notes", "tasks", "expenses")


@dataclass(frozen=True)
class Hit:
    type: str  # one of SEARCH_TYPES
    id: int
    title: str
    snippet: str
    activity_id: Optional[int] = None
    activity_title: Optional[str] = None
    document_id: Optional[int] = None  # for hits found in extracted information


def _like(column, pattern):
    return column.ilike(pattern, escape="\\")


def search_user_data(db: Session, user_id: int, query: str, types: Iterable[str], limit: int) -> List[Hit]:
    pattern = like_pattern(query)
    wanted = [t for t in SEARCH_TYPES if t in set(types)]
    hits: List[Hit] = []

    if "activities" in wanted:
        for a in db.scalars(
            select(Activity)
            .where(Activity.user_id == user_id, or_(_like(Activity.title, pattern), _like(Activity.description, pattern)))
            .order_by(Activity.updated_at.desc(), Activity.id.desc()).limit(limit)
        ):
            hits.append(Hit("activities", a.id, a.title, make_snippet(a.description or a.title, query), a.id, a.title))

    if "documents" in wanted:
        rows = db.execute(
            select(Document, Activity.title)
            .outerjoin(Activity, Activity.id == Document.activity_id)
            .where(Document.user_id == user_id,
                   or_(_like(Document.original_filename, pattern), _like(Document.extracted_text, pattern)))
            .order_by(Document.id.desc()).limit(limit)
        ).all()
        for d, activity_title in rows:
            source = d.extracted_text if d.extracted_text and query.lower() in d.extracted_text.lower() else d.original_filename
            hits.append(Hit("documents", d.id, d.original_filename, make_snippet(source, query),
                            d.activity_id, activity_title, d.id))

    if "extracted" in wanted:
        rows = db.execute(
            select(ExtractedInformation, Document, Activity.title)
            .join(Document, Document.id == ExtractedInformation.document_id)
            .outerjoin(Activity, Activity.id == Document.activity_id)
            .where(Document.user_id == user_id,
                   or_(_like(ExtractedInformation.value, pattern), _like(ExtractedInformation.context, pattern)))
            .order_by(ExtractedInformation.id.desc()).limit(limit)
        ).all()
        for item, d, activity_title in rows:
            hits.append(Hit("extracted", item.id, f"{item.info_type.title().replace('_', ' ')}: {item.value}",
                            make_snippet(item.context or item.value, query), d.activity_id, activity_title, d.id))

    if "notes" in wanted:
        for n, activity_title in db.execute(
            select(Note, Activity.title).join(Activity, Activity.id == Note.activity_id)
            .where(Activity.user_id == user_id, or_(_like(Note.title, pattern), _like(Note.content, pattern)))
            .order_by(Note.updated_at.desc(), Note.id.desc()).limit(limit)
        ).all():
            hits.append(Hit("notes", n.id, n.title, make_snippet(n.content or n.title, query), n.activity_id, activity_title))

    if "tasks" in wanted:
        for t, activity_title in db.execute(
            select(Task, Activity.title).join(Activity, Activity.id == Task.activity_id)
            .where(Activity.user_id == user_id, or_(_like(Task.title, pattern), _like(Task.description, pattern)))
            .order_by(Task.updated_at.desc(), Task.id.desc()).limit(limit)
        ).all():
            hits.append(Hit("tasks", t.id, t.title, make_snippet(t.description or t.title, query), t.activity_id, activity_title))

    if "expenses" in wanted:
        for e, activity_title in db.execute(
            select(Expense, Activity.title).join(Activity, Activity.id == Expense.activity_id)
            .where(Activity.user_id == user_id, or_(_like(Expense.description, pattern), _like(Expense.category, pattern)))
            .order_by(Expense.expense_date.desc(), Expense.id.desc()).limit(limit)
        ).all():
            hits.append(Hit("expenses", e.id, e.description, f"{e.amount} on {e.expense_date}"
                            + (f" ({e.category})" if e.category else ""), e.activity_id, activity_title))
    return hits
