"""Login state: Streamlit session + an optional browser cookie so a refresh does not log the user out.

How it works
  * after login the JWT is kept in st.session_state AND (if the cookie helper is installed) in a browser cookie
    whose lifetime equals the token's lifetime;
  * on a fresh page load / refresh the session is empty, so the cookie is read, the token is checked with
    GET /auth/me, and the user is logged in again. An expired or invalid token is deleted.

Security trade-off (state this in the report): a cookie written from the browser cannot be HttpOnly, so
JavaScript running on the page could read it. Cogniflow shows user text only through Streamlit's own escaped
widgets (never raw HTML), which keeps that risk low. The JWT lives only 60 minutes by default.

To switch persistence off completely set the environment variable COGNIFLOW_PERSIST_LOGIN=0 (refresh = log out).
If the package streamlit-cookies-controller is not installed, the app silently falls back to that behaviour.

Login and logout deliberately do NOT call st.rerun(): a rerun can stop the browser from receiving the cookie
change. Instead the script continues in the same run (see app.py).
"""
import os
from typing import Optional

import streamlit as st

import api_client as api

COOKIE_NAME = "cogniflow_token"
PERSIST = os.getenv("COGNIFLOW_PERSIST_LOGIN", "1") != "0"


def cookie_controller():
    """The cookie helper, or None when persistence is off or the package is missing."""
    if not PERSIST:
        return None
    try:
        from streamlit_cookies_controller import CookieController
    except ImportError:
        return None
    try:
        return CookieController(key="cogniflow_cookies")
    except Exception:  # a broken helper must never break the app
        return None


def is_logged_in() -> bool:
    return "token" in st.session_state


def request_logout(message: str = "You have been logged out.") -> None:
    """Button / 401 callback: only sets a flag. The work happens at the top of the next run (init)."""
    st.session_state["_do_logout"] = True
    st.session_state["flash"] = message


def _safe(action, *args, **kwargs) -> None:
    try:
        action(*args, **kwargs)
    except Exception:
        pass  # cookie problems must never crash the page


def init(ctrl) -> None:
    """Run once at the top of every script run, before anything is drawn."""
    if st.session_state.pop("_do_logout", False):
        st.session_state.pop("token", None)
        st.session_state.pop("user", None)
        st.session_state["_logged_out"] = True  # do not restore from the cookie while it is being deleted
        if ctrl is not None:
            _safe(ctrl.remove, COOKIE_NAME)
        return

    if is_logged_in():
        return

    saved = _saved_token(ctrl)
    if st.session_state.get("_logged_out"):
        if saved is None:  # the cookie is gone: logout is complete
            st.session_state.pop("_logged_out", None)
        return
    if not saved:
        return
    try:
        user = api.me(saved)
    except api.ApiError as e:
        if e.status_code == 401:  # expired or invalid: delete it
            _safe(ctrl.remove, COOKIE_NAME)
        return  # backend down etc.: show the login page; the cookie is kept for the next try
    st.session_state["token"] = saved
    st.session_state["user"] = user


def _saved_token(ctrl) -> Optional[str]:
    if ctrl is None:
        return None
    try:
        value = ctrl.get(COOKIE_NAME)
    except Exception:
        return None
    return value if isinstance(value, str) and value else None


def start(ctrl, token: str, user: dict, expires_in: Optional[int]) -> None:
    """Called after a successful login."""
    st.session_state["token"] = token
    st.session_state["user"] = user
    st.session_state.pop("_logged_out", None)
    if ctrl is not None:
        try:
            ctrl.set(COOKIE_NAME, token, max_age=int(expires_in or 3600), same_site="strict")
        except TypeError:  # older helper version without these options
            _safe(ctrl.set, COOKIE_NAME, token)
        except Exception:
            pass
