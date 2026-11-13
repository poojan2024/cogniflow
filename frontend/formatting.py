"""Display helpers (pure Python, no Streamlit): dates, money, labels, colours.

User-supplied text is never put into HTML. Colours use Streamlit's safe ':red[text]' markdown syntax,
and only on fixed words that this file defines.
"""
import re
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Optional

ACTIVITY_TYPES = ["PROJECT", "EXAM", "TRIP", "MEETING", "APPOINTMENT", "EVENT", "PERSONAL", "CUSTOM"]
ACTIVITY_STATUSES = ["NOT_STARTED", "ACTIVE", "ON_HOLD", "COMPLETED", "CANCELLED"]
SORT_OPTIONS = {"Newest first": "created", "Deadline": "deadline", "Priority": "priority", "Title": "title"}

_TYPE_ICONS = {"PROJECT": "📁", "EXAM": "📝", "TRIP": "✈️", "MEETING": "👥", "APPOINTMENT": "🩺",
               "EVENT": "🎉", "PERSONAL": "🙂", "CUSTOM": "🧩"}
_LEVEL_COLOURS = {"CRITICAL": "red", "HIGH": "orange", "MEDIUM": "blue", "LOW": "gray"}
_STATUS_COLOURS = {"NOT_STARTED": "gray", "ACTIVE": "green", "ON_HOLD": "orange", "COMPLETED": "blue", "CANCELLED": "red"}
_PRIORITY_WORDS = {1: "Very low", 2: "Low", 3: "Medium", 4: "High", 5: "Very high"}


def nice(value: Optional[str]) -> str:
    """'NOT_STARTED' -> 'Not started'."""
    return (value or "").replace("_", " ").capitalize()


def type_label(activity_type: str) -> str:
    return f"{_TYPE_ICONS.get(activity_type, '🧩')} {nice(activity_type)}"


def status_label(status: str) -> str:
    return f":{_STATUS_COLOURS.get(status, 'gray')}[{nice(status)}]"


def level_label(level: str) -> str:
    return f":{_LEVEL_COLOURS.get(level, 'gray')}[**{nice(level)}**]"


def priority_text(priority: int) -> str:
    return f"{_PRIORITY_WORDS.get(priority, str(priority))} ({priority}/5)"


def parse_date(value) -> Optional[date]:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def format_date(value) -> str:
    d = parse_date(value)
    return f"{d.day} {d.strftime('%b %Y')}" if d else "—"


def format_datetime(value) -> str:
    """ISO timestamp from the API (UTC) -> '14 Oct 2026, 10:30' in the computer's local time."""
    if not value:
        return "—"
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)
    if dt.tzinfo is not None:
        dt = dt.astimezone()
    return f"{dt.day} {dt.strftime('%b %Y, %H:%M')}"


def days_left_text(days_left: int) -> str:
    if days_left < 0:
        n = -days_left
        return f"overdue by {n} day{'s' if n != 1 else ''}"
    if days_left == 0:
        return "due today"
    if days_left == 1:
        return "due tomorrow"
    return f"in {days_left} days"


def to_number(value) -> float:
    """The API sends money as a string (exact decimal). Convert only for display and charts."""
    try:
        return float(Decimal(str(value)))
    except (InvalidOperation, ValueError, TypeError):
        return 0.0


def format_money(value) -> str:
    return f"₹{to_number(value):,.2f}"


def short(text: Optional[str], limit: int = 160) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


# ------------------------------------------------------------- workspace helpers
TASK_STATUSES = ["PENDING", "IN_PROGRESS", "COMPLETED"]
PRIORITY_LEVELS = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]  # most to least urgent

# Shown to the user next to the score breakdown. These MIRROR backend/app/services/priority.py (LEVEL_THRESHOLDS);
# tests/test_workspace.py fails if the two ever differ, so the screen can never explain the wrong rule.
LEVEL_THRESHOLDS = (("CRITICAL", 80), ("HIGH", 60), ("MEDIUM", 35))


def thresholds_text() -> str:
    parts = [f"{nice(level)} from {minimum}" for level, minimum in LEVEL_THRESHOLDS]
    return ", ".join(parts) + ", otherwise Low"


def days_until(due, today: Optional[date] = None) -> Optional[int]:
    d = parse_date(due)
    return None if d is None else (d - (today or date.today())).days


def to_local(value) -> Optional[datetime]:
    """ISO timestamp from the API (UTC) -> timezone-aware datetime in the computer's local time zone."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.astimezone() if dt.tzinfo else dt.replace(tzinfo=None).astimezone()


def local_iso(day: date, at: time) -> str:
    """A date and time typed by the user (computer's local time) -> ISO text WITH a time-zone offset.
    The backend refuses reminder times that do not say which time zone they are in."""
    return datetime.combine(day, at.replace(second=0, microsecond=0)).astimezone().isoformat()


def is_past(day: date, at: time) -> bool:
    return datetime.combine(day, at).astimezone() <= datetime.now().astimezone()


# ------------------------------------------------------------- document helpers
# These mirror the backend (services/file_validation.py ALLOWED and core/config.py max_upload_mb).
# tests/test_documents.py fails if they ever differ, so the upload form never promises what the server refuses.
UPLOAD_TYPES = ["pdf", "png", "jpg", "jpeg", "txt"]
MAX_UPLOAD_MB = 10

DOC_IN_PROGRESS = ("UPLOADED", "PROCESSING")
_DOC_STATUS = {
    "UPLOADED": ("⏳", "Queued", "gray"),
    "PROCESSING": ("⚙️", "Processing", "blue"),
    "PROCESSED": ("✅", "Processed", "green"),
    "NEEDS_REVIEW": ("⚠️", "Needs review", "orange"),
    "FAILED": ("❌", "Failed", "red"),
}
INFO_ORDER = ["DOCUMENT_TYPE", "DEADLINE", "DATE", "AMOUNT", "PERSON", "LOCATION", "KEYWORD", "OTHER"]
_CONFIDENCE_COLOURS = {"strong": "green", "moderate": "orange", "weak": "gray"}


def doc_status_label(status: str) -> str:
    icon, text, colour = _DOC_STATUS.get(status, ("", nice(status), "gray"))
    return f"{icon} :{colour}[{text}]"


def method_text(doc: dict) -> str:
    method = doc.get("extraction_method")
    if method == "TEXT":
        return "Text extraction (the file contains real text)"
    if method == "OCR":
        conf = doc.get("ocr_confidence")
        return "OCR (scanned page or image)" + (f" · engine confidence {conf:.0f}/100" if conf is not None else "")
    return "No text extracted"


def match_label(confidence: str) -> str:
    return f":{_CONFIDENCE_COLOURS.get(confidence, 'gray')}[**{nice(confidence)} match**]"


def human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB"):
        if size < 1024 or unit == "MB":
            return f"{int(size)} B" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{num_bytes} B"


_MD_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+!|>~$<&])")


def md_escape(text: Optional[str]) -> str:
    """Make text from an UNTRUSTED document safe to show with st.markdown / st.caption.

    A PDF sent by someone else could contain markdown such as an image link that makes the browser contact a remote
    server, or a misleading link. Escaping the special characters shows the text exactly as it is written."""
    return _MD_SPECIAL.sub(r"\\\1", text or "")


# ------------------------------------------------------- assistant / history / search
_HISTORY_ICONS = {"ACTIVITY": "📁", "DOCUMENT": "📄", "SUGGESTION": "🎯", "TASK": "✅", "NOTE": "📝",
                  "EXPENSE": "💰", "REMINDER": "⏰", "ASSISTANT": "🤖"}
SEARCH_TYPES = {"activities": "Activities", "documents": "Documents", "extracted": "Extracted information",
                "notes": "Notes", "tasks": "Tasks", "expenses": "Expenses"}  # mirrors the backend; checked by a test


def history_icon(action: str) -> str:
    return _HISTORY_ICONS.get((action or "").split("_")[0], "•")


def md_block(text: Optional[str]) -> str:
    """Untrusted multi-line text (an AI answer, a note from a document) -> safe markdown that keeps its line breaks."""
    return md_escape(text).replace("\n", "  \n")
