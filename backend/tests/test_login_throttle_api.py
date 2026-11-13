"""HTTP-level tests: the limiter as seen through POST /auth/login."""
import re

import pytest

from app.core.config import get_settings
from tests.conftest import PASSWORD, login, register

WRONG = "Wr0ngPassword"


def _fail(client, email, times):
    for _ in range(times):
        assert login(client, email, WRONG).status_code == 401


def test_sixth_attempt_after_five_failures_is_refused_with_retry_after(client):
    register(client)
    _fail(client, "alice@example.com", 5)
    res = login(client, "alice@example.com", WRONG)
    assert res.status_code == 429
    assert "Too many failed login attempts" in res.json()["detail"]
    assert 1 <= int(res.headers["Retry-After"]) <= 15 * 60


def test_the_correct_password_is_also_refused_while_blocked(client):
    register(client)
    _fail(client, "alice@example.com", 5)
    assert login(client, "alice@example.com", PASSWORD).status_code == 429


def test_refusal_happens_before_any_password_work(client, monkeypatch):
    register(client)
    _fail(client, "alice@example.com", 5)

    def must_not_run(*args, **kwargs):
        raise AssertionError("the password was checked even though the login is blocked")

    monkeypatch.setattr("app.routers.auth.verify_password", must_not_run)
    assert login(client, "alice@example.com", PASSWORD).status_code == 429


def test_failures_below_the_limit_do_not_block_and_a_success_resets_the_count(client):
    register(client)
    _fail(client, "alice@example.com", 4)
    assert login(client, "alice@example.com", PASSWORD).status_code == 200
    _fail(client, "alice@example.com", 4)                 # still 401 (not 429): the earlier four were forgotten
    assert login(client, "alice@example.com", PASSWORD).status_code == 200


def test_unknown_emails_are_limited_the_same_way(client):
    _fail(client, "nobody@example.com", 5)
    res = login(client, "nobody@example.com", WRONG)
    assert res.status_code == 429                         # nothing reveals that this account does not exist


def test_email_case_and_spaces_do_not_dodge_the_limit(client):
    register(client)
    for variant in ("alice@example.com", "ALICE@example.com", " alice@example.com ", "Alice@Example.com", "alice@EXAMPLE.com"):
        assert login(client, variant, WRONG).status_code == 401
    assert login(client, "AlIcE@example.com", WRONG).status_code == 429


def test_another_account_is_not_affected(client):
    register(client)
    register(client, email="bob@example.com", name="Bob")
    _fail(client, "alice@example.com", 5)
    assert login(client, "alice@example.com", WRONG).status_code == 429
    assert login(client, "bob@example.com", PASSWORD).status_code == 200


def test_an_existing_token_keeps_working_while_the_login_is_blocked(client):
    register(client)
    token = login(client, "alice@example.com", PASSWORD).json()["access_token"]
    _fail(client, "alice@example.com", 5)
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200


def test_the_limits_come_from_settings(client, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "login_max_failures", 2)
    register(client)
    _fail(client, "alice@example.com", 2)
    assert login(client, "alice@example.com", WRONG).status_code == 429


def test_the_blocked_message_never_contains_a_password_or_email(client):
    register(client)
    _fail(client, "alice@example.com", 5)
    body = login(client, "alice@example.com", WRONG).text
    assert WRONG not in body and "alice@example.com" not in body


def test_default_limits_are_five_failures_in_fifteen_minutes():
    settings = get_settings()
    assert (settings.login_max_failures, settings.login_window_minutes) == (5, 15)


def test_zero_or_negative_limits_are_rejected():
    from app.core.config import Settings

    for field in ("login_max_failures", "login_window_minutes"):
        with pytest.raises(ValueError):
            Settings(database_url="sqlite://", jwt_secret="x" * 40, **{field: 0})
