"""Password hashing (bcrypt) and JWT creation / validation (PyJWT)."""
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt

from app.core.config import get_settings


class TokenExpiredError(Exception):
    pass


class TokenInvalidError(Exception):
    pass


# ---------------------------------------------------------------- passwords
def hash_password(password: str) -> str:
    """Return a salted bcrypt hash. The plain password is never stored."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:  # password over the 72-byte bcrypt limit, or a malformed hash
        return False


# Used to spend the same time on login attempts for unknown emails (prevents user enumeration by timing).
DUMMY_HASH = hash_password("cogniflow-dummy-password-1")


# ---------------------------------------------------------------------- JWT
def create_access_token(user_id: int, expires_delta: Optional[timedelta] = None) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    lifetime = expires_delta if expires_delta is not None else timedelta(minutes=settings.access_token_expire_minutes)
    payload = {"sub": str(user_id), "iat": now, "exp": now + lifetime, "type": "access"}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> int:
    """Validate signature, algorithm and expiry; return the user id.

    Raises TokenExpiredError or TokenInvalidError.
    """
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],  # fixed algorithm list blocks "alg: none" tricks
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpiredError() from exc
    except jwt.InvalidTokenError as exc:
        raise TokenInvalidError() from exc

    if payload.get("type") != "access":
        raise TokenInvalidError()
    try:
        return int(payload["sub"])
    except (TypeError, ValueError) as exc:
        raise TokenInvalidError() from exc
