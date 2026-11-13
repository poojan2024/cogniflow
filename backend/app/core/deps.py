"""Reusable FastAPI dependencies (authentication)."""
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import TokenExpiredError, TokenInvalidError, decode_access_token
from app.models import Activity, Document, User
from app.services.gemini_client import GeminiClient, build_client

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def _unauthorized(message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=message,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    """Every protected endpoint depends on this. Returns the logged-in user or raises 401."""
    try:
        user_id = decode_access_token(token)
    except TokenExpiredError:
        raise _unauthorized("Your session has expired. Please log in again.")
    except TokenInvalidError:
        raise _unauthorized("Invalid authentication token.")

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise _unauthorized("Invalid authentication token.")
    return user


def get_owned_activity(
    activity_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Activity:
    """Load an activity ONLY if it belongs to the logged-in user.

    Every nested endpoint (/activities/{activity_id}/tasks, /notes, ...) depends on this, so ownership is
    checked in one place. Someone else's activity returns 404 (not 403), so its existence is not revealed.
    """
    activity = db.scalar(
        select(Activity).where(Activity.id == activity_id, Activity.user_id == current_user.id)
    )
    if activity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Activity not found.")
    return activity


def get_owned_document(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Document:
    """Load a document ONLY if it belongs to the logged-in user (404 otherwise, so existence is not revealed)."""
    document = db.scalar(
        select(Document).where(Document.id == document_id, Document.user_id == current_user.id)
    )
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    return document


def get_ai_client() -> Optional[GeminiClient]:
    """The Gemini client, or None when no usable GEMINI_API_KEY is configured (the assistant then uses keyword mode).
    Tests replace this dependency, so they never call Google."""
    settings = get_settings()
    return build_client(settings.gemini_api_key.get_secret_value(), settings.gemini_model, settings.ai_timeout_seconds)
