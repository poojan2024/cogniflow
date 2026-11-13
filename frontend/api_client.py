"""Thin HTTP client for the Cogniflow API. The JWT is sent as a Bearer token.

This module never imports Streamlit, so it can be tested on its own (see tests/test_api_client.py).
Every function that needs a login takes the token as its first argument.
"""
import os
from datetime import date
from decimal import Decimal
from typing import Any, Dict, Optional

import requests

API_URL = os.getenv("COGNIFLOW_API_URL", "http://127.0.0.1:8000")
TIMEOUT = 15
AI_TIMEOUT = 45  # the backend waits up to 30 s for Gemini before it falls back, so wait a little longer
UPLOAD_TIMEOUT = 60  # uploading / downloading a file can take longer than a normal call


class ApiError(Exception):
    """An error message that is safe to show to the user."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


def _error_text(res: requests.Response) -> str:
    try:
        body = res.json()
    except ValueError:
        return "Unexpected response from the server."
    if not isinstance(body, dict):
        return "Request failed."
    errors = body.get("errors")
    if errors:
        return " ".join(e.get("message", "") for e in errors)
    detail = body.get("detail", "Request failed.")
    return detail if isinstance(detail, str) else "Request failed."


def request(method: str, path: str, token: Optional[str] = None, **kwargs):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    timeout = kwargs.pop("timeout", TIMEOUT)
    try:
        res = requests.request(method, f"{API_URL}{path}", headers=headers, timeout=timeout, **kwargs)
    except requests.exceptions.RequestException:
        raise ApiError("Cannot reach the Cogniflow server. Please make sure the backend is running.")
    if res.status_code >= 400:
        raise ApiError(_error_text(res), res.status_code)
    return res.json() if res.content else None


# ------------------------------------------------------------------ account
def register(email: str, full_name: str, password: str):
    return request("POST", "/auth/register", json={"email": email, "full_name": full_name, "password": password})


def login_full(email: str, password: str) -> Dict[str, Any]:
    """Returns {"access_token": ..., "token_type": "bearer", "expires_in": seconds}."""
    return request("POST", "/auth/login", data={"username": email, "password": password})


def login(email: str, password: str) -> str:
    return login_full(email, password)["access_token"]


def me(token: str):
    return request("GET", "/auth/me", token=token)


# ---------------------------------------------------------------- dashboard
def dashboard(token: str):
    return request("GET", "/dashboard", token=token)


# --------------------------------------------------------------- activities
def _iso(value: Any) -> Any:
    """Dates / datetimes -> ISO text, exact decimals -> text. Everything else is sent unchanged."""
    if isinstance(value, Decimal):
        return str(value)
    return value.isoformat() if isinstance(value, date) else value  # datetime is a subclass of date


def _clean(data: Dict[str, Any]) -> Dict[str, Any]:
    return {k: _iso(v) for k, v in data.items()}


def list_activities(
    token: str,
    q: str = "",
    activity_type: Optional[str] = None,
    status: Optional[str] = None,
    sort: str = "created",
    page: int = 1,
    page_size: int = 10,
):
    params = {"sort": sort, "page": page, "page_size": page_size}
    if q and q.strip():
        params["q"] = q.strip()
    if activity_type:
        params["activity_type"] = activity_type
    if status:
        params["status"] = status
    return request("GET", "/activities", token=token, params=params)


def create_activity(token: str, data: Dict[str, Any]):
    return request("POST", "/activities", token=token, json={k: _iso(v) for k, v in data.items()})


def update_activity(token: str, activity_id: int, data: Dict[str, Any]):
    return request("PATCH", f"/activities/{activity_id}", token=token, json={k: _iso(v) for k, v in data.items()})


def delete_activity(token: str, activity_id: int):
    return request("DELETE", f"/activities/{activity_id}", token=token)


def get_activity(token: str, activity_id: int):
    return request("GET", f"/activities/{activity_id}", token=token)


# -------------------------------------------------------------------- tasks
def list_tasks(token: str, activity_id: int, status_filter: Optional[str] = None,
               priority_level: Optional[str] = None, sort: str = "priority"):
    params = {"sort": sort}
    if status_filter:
        params["status_filter"] = status_filter
    if priority_level:
        params["priority_level"] = priority_level
    return request("GET", f"/activities/{activity_id}/tasks", token=token, params=params)


def create_task(token: str, activity_id: int, data: Dict[str, Any]):
    return request("POST", f"/activities/{activity_id}/tasks", token=token, json=_clean(data))


def update_task(token: str, activity_id: int, task_id: int, data: Dict[str, Any]):
    """Only the keys in `data` are changed. {"manual_priority": None} clears the manual override."""
    return request("PATCH", f"/activities/{activity_id}/tasks/{task_id}", token=token, json=_clean(data))


def delete_task(token: str, activity_id: int, task_id: int):
    return request("DELETE", f"/activities/{activity_id}/tasks/{task_id}", token=token)


# -------------------------------------------------------------------- notes
def list_notes(token: str, activity_id: int, q: str = ""):
    params = {"q": q.strip()} if q and q.strip() else {}
    return request("GET", f"/activities/{activity_id}/notes", token=token, params=params)


def create_note(token: str, activity_id: int, data: Dict[str, Any]):
    return request("POST", f"/activities/{activity_id}/notes", token=token, json=_clean(data))


def update_note(token: str, activity_id: int, note_id: int, data: Dict[str, Any]):
    return request("PATCH", f"/activities/{activity_id}/notes/{note_id}", token=token, json=_clean(data))


def delete_note(token: str, activity_id: int, note_id: int):
    return request("DELETE", f"/activities/{activity_id}/notes/{note_id}", token=token)


# ----------------------------------------------------------------- expenses
def list_expenses(token: str, activity_id: int):
    """Returns {"items": [...], "count": n, "total_amount": "exact decimal as text"}."""
    return request("GET", f"/activities/{activity_id}/expenses", token=token)


def create_expense(token: str, activity_id: int, data: Dict[str, Any]):
    return request("POST", f"/activities/{activity_id}/expenses", token=token, json=_clean(data))


def update_expense(token: str, activity_id: int, expense_id: int, data: Dict[str, Any]):
    return request("PATCH", f"/activities/{activity_id}/expenses/{expense_id}", token=token, json=_clean(data))


def delete_expense(token: str, activity_id: int, expense_id: int):
    return request("DELETE", f"/activities/{activity_id}/expenses/{expense_id}", token=token)


# ---------------------------------------------------------------- reminders
def list_reminders(token: str, activity_id: int):
    return request("GET", f"/activities/{activity_id}/reminders", token=token)


def create_reminder(token: str, activity_id: int, data: Dict[str, Any]):
    """data["remind_at"] must be an ISO time WITH a time-zone offset (the backend rejects times without one)."""
    return request("POST", f"/activities/{activity_id}/reminders", token=token, json=_clean(data))


def update_reminder(token: str, activity_id: int, reminder_id: int, data: Dict[str, Any]):
    return request("PATCH", f"/activities/{activity_id}/reminders/{reminder_id}", token=token, json=_clean(data))


def delete_reminder(token: str, activity_id: int, reminder_id: int):
    return request("DELETE", f"/activities/{activity_id}/reminders/{reminder_id}", token=token)


# ---------------------------------------------------------------- documents
def upload_document(token: str, filename: str, data: bytes, content_type: str, activity_id: Optional[int] = None):
    """Uploads a file. The backend validates the real content, stores the file and starts processing in the background:
    the returned document has status UPLOADED and must be polled with get_document()."""
    form = {"activity_id": str(activity_id)} if activity_id is not None else None
    return request("POST", "/documents", token=token, files={"file": (filename, data, content_type)}, data=form,
                   timeout=UPLOAD_TIMEOUT)


def list_documents(token: str, activity_id: Optional[int] = None, unassigned: bool = False,
                   status: Optional[str] = None, page: int = 1, page_size: int = 10):
    params = {"page": page, "page_size": page_size}
    if activity_id is not None:
        params["activity_id"] = activity_id
    if unassigned:
        params["unassigned"] = "true"
    if status:
        params["status"] = status
    return request("GET", "/documents", token=token, params=params)


def get_document(token: str, document_id: int):
    return request("GET", f"/documents/{document_id}", token=token)


def download_document(token: str, document_id: int) -> bytes:
    """The stored file itself (the backend checks that it belongs to the logged-in user)."""
    try:
        res = requests.get(f"{API_URL}/documents/{document_id}/download",
                           headers={"Authorization": f"Bearer {token}"}, timeout=UPLOAD_TIMEOUT)
    except requests.exceptions.RequestException:
        raise ApiError("Cannot reach the Cogniflow server. Please make sure the backend is running.")
    if res.status_code >= 400:
        raise ApiError(_error_text(res), res.status_code)
    return res.content


def correct_document_text(token: str, document_id: int, text: str):
    return request("PATCH", f"/documents/{document_id}/text", token=token, json={"text": text})


def reprocess_document(token: str, document_id: int):
    return request("POST", f"/documents/{document_id}/reprocess", token=token)


def assign_document(token: str, document_id: int, activity_id: Optional[int]):
    """Put the document into an activity (the user's own choice). None removes it from its activity."""
    return request("PATCH", f"/documents/{document_id}", token=token, json={"activity_id": activity_id})


def delete_document_item(token: str, document_id: int, item_id: int):
    return request("DELETE", f"/documents/{document_id}/items/{item_id}", token=token)


def delete_document(token: str, document_id: int):
    return request("DELETE", f"/documents/{document_id}", token=token)


def list_suggestions(token: str, document_id: int):
    return request("GET", f"/documents/{document_id}/suggestions", token=token)


def refresh_suggestions(token: str, document_id: int):
    return request("POST", f"/documents/{document_id}/suggestions", token=token)


def confirm_suggestion(token: str, document_id: int, suggestion_id: int):
    return request("POST", f"/documents/{document_id}/suggestions/{suggestion_id}/confirm", token=token)


def reject_suggestion(token: str, document_id: int, suggestion_id: int):
    return request("POST", f"/documents/{document_id}/suggestions/{suggestion_id}/reject", token=token)


# ---------------------------------------------------------------- assistant
def assistant_status(token: str):
    """Whether Gemini is configured on the server (never reveals the key)."""
    return request("GET", "/assistant/status", token=token)


def ask_assistant(token: str, activity_id: int, question: str, mode: str = "auto"):
    """mode "auto" = Gemini if available (the activity's data is sent to Google); "local" = keyword search, nothing is sent."""
    return request("POST", f"/activities/{activity_id}/assistant/ask", token=token,
                   json={"question": question, "mode": mode}, timeout=AI_TIMEOUT)


def assistant_context(token: str, activity_id: int):
    """Exactly the stored data that would be sent to Gemini together with a question."""
    return request("GET", f"/activities/{activity_id}/assistant/context", token=token)


def assistant_history(token: str, activity_id: int, page: int = 1, page_size: int = 5):
    return request("GET", f"/activities/{activity_id}/assistant/history", token=token,
                   params={"page": page, "page_size": page_size})


def delete_interaction(token: str, activity_id: int, interaction_id: int):
    return request("DELETE", f"/activities/{activity_id}/assistant/history/{interaction_id}", token=token)


# ------------------------------------------------------------------ history
def activity_history(token: str, activity_id: int, page: int = 1, page_size: int = 20):
    return request("GET", f"/activities/{activity_id}/history", token=token, params={"page": page, "page_size": page_size})


# ------------------------------------------------------------------- search
def search(token: str, q: str, types: Optional[str] = None, limit: int = 10):
    """types is a comma-separated subset of: activities, documents, extracted, notes, tasks, expenses."""
    params = {"q": q, "limit": limit}
    if types:
        params["types"] = types
    return request("GET", "/search", token=token, params=params)


# ----------------------------------------------------------- notifications
def list_notifications(token: str, unread_only: bool = False, page: int = 1, page_size: int = 20):
    """Loading them also turns any due reminders into notifications (done by the backend)."""
    params = {"page": page, "page_size": page_size}
    if unread_only:
        params["unread_only"] = "true"
    return request("GET", "/notifications", token=token, params=params)


def mark_notification_read(token: str, notification_id: int):
    return request("POST", f"/notifications/{notification_id}/read", token=token)


def mark_all_notifications_read(token: str):
    return request("POST", "/notifications/read-all", token=token)


def delete_notification(token: str, notification_id: int):
    return request("DELETE", f"/notifications/{notification_id}", token=token)
