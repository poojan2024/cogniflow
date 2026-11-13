"""The contextual AI assistant of one activity.

How an answer is produced (POST /activities/{id}/assistant/ask):
  1. the activity must belong to the logged-in user;
  2. the rate limit is checked (protects the API key);
  3. the context is built from THIS activity's stored data only;
  4. mode "auto": the context and the question are sent to Gemini with strict "answer only from the data" rules.
     mode "local": nothing is sent anywhere; a keyword search over the same data answers instead;
  5. if Gemini is not configured, unreachable, rate-limited or returns nothing usable, the user gets a clear notice
     plus a keyword-based answer, and the application keeps working;
  6. every question and answer is stored (ai_interactions) and recorded in the activity history.
"""
import logging
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.deps import get_ai_client, get_current_user, get_owned_activity
from app.models import Activity, AIInteraction, User
from app.schemas.assistant import (
    AnswerOut,
    AskRequest,
    AssistantStatusOut,
    ContextOut,
    InteractionOut,
    InteractionPage,
    ReferenceOut,
)
from app.services.assistant_context import build_context
from app.services.assistant_core import build_prompts, check_citations, clip, says_not_available
from app.services.gemini_client import AIError
from app.services.history import log_event
from app.services.keyword_answer import answer_from_keywords

logger = logging.getLogger("cogniflow")

router = APIRouter(prefix="/activities/{activity_id}/assistant", tags=["assistant"])
status_router = APIRouter(prefix="/assistant", tags=["assistant"])

MAX_ANSWER_CHARS = 6000
LOCAL_NOTE = "Answered with keyword search only. Nothing was sent to Gemini."


def _hourly_limit() -> int:
    return get_settings().ai_max_questions_per_hour


def _source(db_status: str, note: Optional[str]) -> str:
    return "gemini" if db_status == "SUCCESS" and not note else "keyword"


def _refs(items) -> List[ReferenceOut]:
    return [ReferenceOut(label=i.label, kind=i.kind, title=i.title) for i in items]


@status_router.get("/status", response_model=AssistantStatusOut)
def assistant_status(ai_client=Depends(get_ai_client), current_user: User = Depends(get_current_user)):
    """Whether Gemini is configured on the server. Never reveals the key."""
    settings = get_settings()
    configured = ai_client is not None
    return AssistantStatusOut(
        provider="gemini",
        ai_configured=configured,
        model=settings.gemini_model,
        max_questions_per_hour=_hourly_limit(),
        note=("Questions in mode 'auto' send the selected activity's data to Google Gemini. Mode 'local' sends nothing."
              if configured else "Gemini is not configured on the server; the assistant answers with keyword search."),
    )


@router.post("/ask", response_model=AnswerOut)
def ask(
    payload: AskRequest,
    activity: Activity = Depends(get_owned_activity),
    db: Session = Depends(get_db),
    ai_client=Depends(get_ai_client),
):
    settings = get_settings()
    now = datetime.now(timezone.utc)

    recent = db.scalar(
        select(func.count()).select_from(AIInteraction).join(Activity, Activity.id == AIInteraction.activity_id)
        .where(Activity.user_id == activity.user_id, AIInteraction.created_at >= now - timedelta(hours=1))
    ) or 0
    if recent >= _hourly_limit():
        raise HTTPException(
            status_code=429,
            detail="You have asked many questions in the last hour. Please wait a while, or use mode 'local'.",
        )

    bundle = build_context(db, activity, date.today(), settings.ai_context_max_chars)

    answer: Optional[str] = None
    db_status, note = "SUCCESS", None
    ai_status, notice = "not_used", None
    verified_items: list = []
    unverified: List[str] = []

    if payload.mode == "local":
        note = notice = LOCAL_NOTE
    else:
        try:
            if ai_client is None:
                raise AIError("not_configured")
            system_prompt, user_prompt = build_prompts(bundle.text, payload.question)
            answer = clip(ai_client.generate(system_prompt, user_prompt), MAX_ANSWER_CHARS)
            if not answer:
                raise AIError("bad_response")
            ai_status = "ok"
            verified_items, unverified = check_citations(answer, bundle)
            if unverified:
                notice = ("Some references in this answer ("
                          + ", ".join(unverified) + ") do not exist in the activity data. Please double-check the answer.")
        except Exception as raised:  # any AI problem, expected or not, must fall back instead of breaking the request
            exc = raised if isinstance(raised, AIError) else AIError("bad_response")
            if exc is not raised:
                logger.exception("Unexpected error while asking the AI assistant")
            answer = None
            db_status = exc.db_status
            ai_status = "failed" if exc.db_status == "FAILED" else "unavailable"
            note = f"{exc.kind}: {exc.user_message}"[:255]
            notice = f"{exc.user_message} Showing a keyword-based answer instead."

    if answer is None:  # local mode, or the AI could not answer
        keyword = answer_from_keywords(payload.question, bundle.items)
        answer = keyword.text
        verified_items = list(keyword.items)
        unverified = []

    interaction = AIInteraction(
        activity_id=activity.id, question=payload.question, answer=answer, status=db_status, error_message=note)
    db.add(interaction)
    db.flush()
    source = _source(db_status, note)
    log_event(db, activity.id, "ASSISTANT_QUESTION", "ai_interaction", interaction.id,
              f"Asked: {clip(payload.question, 120)} (answered by {source})")
    db.commit()
    db.refresh(interaction)

    return AnswerOut(
        id=interaction.id,
        question=payload.question,
        answer=answer,
        source=source,
        ai_status=ai_status,
        notice=notice,
        has_information=bool(verified_items) if source == "keyword" else not says_not_available(answer),
        references=_refs(verified_items),
        unverified_references=unverified,
        context_truncated=bundle.truncated,
        created_at=interaction.created_at,
    )


@router.get("/history", response_model=InteractionPage)
def assistant_history(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    activity: Activity = Depends(get_owned_activity),
    db: Session = Depends(get_db),
):
    base = select(AIInteraction).where(AIInteraction.activity_id == activity.id)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(
        base.order_by(AIInteraction.created_at.desc(), AIInteraction.id.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    items = [
        InteractionOut(id=r.id, question=r.question, answer=r.answer, status=r.status,
                       source=_source(r.status, r.error_message), note=r.error_message, created_at=r.created_at)
        for r in rows
    ]
    return InteractionPage(items=items, total=total, page=page, page_size=page_size)


@router.delete("/history/{interaction_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_interaction(interaction_id: int, activity: Activity = Depends(get_owned_activity), db: Session = Depends(get_db)):
    row = db.scalar(select(AIInteraction).where(
        AIInteraction.id == interaction_id, AIInteraction.activity_id == activity.id))
    if row is None:
        raise HTTPException(status_code=404, detail="Conversation entry not found.")
    db.delete(row)
    db.commit()


@router.get("/context", response_model=ContextOut)
def preview_context(activity: Activity = Depends(get_owned_activity), db: Session = Depends(get_db)):
    """Shows exactly which stored data would be sent to Gemini with a question (transparency for the user)."""
    bundle = build_context(db, activity, date.today(), get_settings().ai_context_max_chars)
    return ContextOut(text=bundle.text, char_count=len(bundle.text), truncated=bundle.truncated, sources=_refs(bundle.items))
