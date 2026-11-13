"""Registration, login and current-user endpoints.

Logout: JWTs are stateless, so logging out means the client discards the token
(the Streamlit app clears its session). Tokens are short-lived to limit exposure.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.security import DUMMY_HASH, create_access_token, hash_password, verify_password
from app.models import User
from app.schemas.auth import RegisterRequest, TokenOut, UserOut
from app.services.login_throttle import login_throttle, throttle_key, too_many_message

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    conflict = HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account with this email already exists.")

    if db.scalar(select(User).where(User.email == email)) is not None:
        raise conflict

    user = User(email=email, full_name=payload.full_name, password_hash=hash_password(payload.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:  # two simultaneous registrations with the same email
        db.rollback()
        raise conflict
    db.refresh(user)
    return user


@router.post("/login", response_model=TokenOut)
def login(request: Request, form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """OAuth2 password form: `username` carries the email (this also makes Swagger's Authorize button work)."""
    email = form.username.strip().lower()
    settings = get_settings()

    # Brute-force protection: too many recent failures for this email + IP -> refuse BEFORE doing any password work.
    window = settings.login_window_minutes * 60
    key = throttle_key(email, request.client.host if request.client else None)
    wait = login_throttle.retry_after(key, settings.login_max_failures, window)
    if wait is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=too_many_message(wait),
            headers={"Retry-After": str(wait)},
        )

    user = db.scalar(select(User).where(User.email == email))

    # Always run one bcrypt check so response time does not reveal whether the email exists.
    password_ok = verify_password(form.password, user.password_hash if user else DUMMY_HASH)

    if user is None or not password_ok or not user.is_active:
        login_throttle.record_failure(key, window)  # unknown emails are counted too, so the limiter reveals nothing
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    login_throttle.clear(key)
    return TokenOut(
        access_token=create_access_token(user.id),
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return current_user
