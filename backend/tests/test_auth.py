"""Tests for registration, login, JWT validation and unauthorized access."""
from datetime import timedelta

import jwt
from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import create_access_token
from app.models import User
from tests.conftest import PASSWORD, auth_header, login, register


# ------------------------------------------------------------ registration
def test_register_success_does_not_expose_password_or_hash(client):
    res = register(client)
    assert res.status_code == 201
    body = res.json()
    assert body["email"] == "alice@example.com"
    assert "password" not in body and "password_hash" not in body


def test_password_is_stored_as_bcrypt_hash(client, db_session):
    register(client)
    user = db_session.scalar(select(User).where(User.email == "alice@example.com"))
    assert user.password_hash != PASSWORD
    assert user.password_hash.startswith("$2")  # bcrypt marker


def test_register_duplicate_email_is_rejected_case_insensitively(client):
    assert register(client, "bob@example.com").status_code == 201
    assert register(client, "BOB@Example.com").status_code == 409


def test_register_weak_password_rejected_and_not_echoed(client):
    res = register(client, password="short")
    assert res.status_code == 422
    assert "short" not in res.text.replace("Password must be at least 8 characters.", "")


def test_register_password_needs_letter_and_digit(client):
    assert register(client, password="onlyletters").status_code == 422
    assert register(client, password="12345678").status_code == 422


def test_register_invalid_email_rejected(client):
    assert register(client, email="not-an-email").status_code == 422


# ------------------------------------------------------------------- login
def test_login_success_returns_bearer_token_and_me_works(client):
    register(client)
    res = login(client)
    assert res.status_code == 200
    assert res.json()["token_type"] == "bearer"
    me = client.get("/auth/me", headers=auth_header(client))
    assert me.status_code == 200
    assert me.json()["email"] == "alice@example.com"


def test_login_wrong_password_and_unknown_email_give_same_message(client):
    register(client)
    wrong_pw = login(client, password="WrongPass1")
    unknown = login(client, email="nobody@example.com")
    assert wrong_pw.status_code == unknown.status_code == 401
    assert wrong_pw.json()["detail"] == unknown.json()["detail"]


def test_inactive_user_cannot_login_or_use_existing_token(client, db_session):
    register(client)
    headers = auth_header(client)
    user = db_session.scalar(select(User))
    user.is_active = False
    db_session.commit()
    assert login(client).status_code == 401
    assert client.get("/auth/me", headers=headers).status_code == 401


# --------------------------------------------------------------- JWT / access
def test_protected_endpoint_without_token_is_401(client):
    assert client.get("/auth/me").status_code == 401


def test_garbage_token_is_401(client):
    res = client.get("/auth/me", headers={"Authorization": "Bearer not.a.jwt"})
    assert res.status_code == 401


def test_expired_token_is_401_with_clear_message(client):
    register(client)
    token = create_access_token(user_id=1, expires_delta=timedelta(seconds=-5))
    res = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 401
    assert "expired" in res.json()["detail"].lower()


def test_tampered_token_is_401(client):
    register(client)
    token = login(client).json()["access_token"]
    tampered = token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB")
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {tampered}"}).status_code == 401


def test_token_signed_with_wrong_secret_is_401(client):
    register(client)
    forged = jwt.encode({"sub": "1", "iat": 1, "exp": 4102444800, "type": "access"}, "x" * 40, algorithm="HS256")
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_alg_none_token_is_401(client):
    register(client)
    forged = jwt.encode({"sub": "1", "iat": 1, "exp": 4102444800, "type": "access"}, key=None, algorithm="none")
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_token_for_deleted_user_is_401(client, db_session):
    register(client)
    headers = auth_header(client)
    db_session.delete(db_session.scalar(select(User)))
    db_session.commit()
    assert client.get("/auth/me", headers=headers).status_code == 401


def test_token_without_expiry_is_rejected(client):
    register(client)
    secret = get_settings().jwt_secret
    no_exp = jwt.encode({"sub": "1", "iat": 1, "type": "access"}, secret, algorithm="HS256")
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {no_exp}"}).status_code == 401


# ------------------------------------------------------------------ misc
def test_health_is_public(client):
    assert client.get("/health").json() == {"status": "ok"}
